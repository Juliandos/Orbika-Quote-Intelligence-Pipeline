#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.seeded_catalog_support import (
    AUTOS_ONLY_NOTE,
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
    build_searchable_tokens,
    canonical_url,
    decode_html,
    extract_meta_content,
    extract_page_title,
    fetch_url,
    iter_json_ld_nodes,
    load_json,
    normalize_text,
    parse_json_ld_blocks,
    product_from_json_ld,
    provider_paths,
    same_host,
    write_snapshot_bundle,
)

PROVIDER_ID = "importadoraeurobrasil"
DISPLAY_NAME = "Importadora EuroBrasil"
LISTING_ROOT_URL = "https://www.importadoraeurobrasil.com/productos/"
PRODUCTS_PER_PAGE = 12
DETAIL_WORKERS = 10

PRODUCT_URL_RE = re.compile(r"https://www\.importadoraeurobrasil\.com/producto/[^\"'#?\s<]+/?", re.IGNORECASE)
LISTING_BLOCK_RE = re.compile(r"<li\b[^>]*class=[\"'][^\"']*\bproduct\b[^\"']*[\"'][^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
RESULT_COUNT_RE = re.compile(r"<p[^>]*class=[\"\'][^\"\']*woocommerce-result-count[^\"\']*[\"\'][^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
PAGINATION_NAV_RE = re.compile(r"<nav class=\"woocommerce-pagination\".*?</nav>", re.IGNORECASE | re.DOTALL)
PAGE_LINK_RE = re.compile(r"href=\"(https://www\.importadoraeurobrasil\.com/productos(?:/page/\d+/?)?)\"", re.IGNORECASE)
TITLE_RE = re.compile(r"<h2[^>]*class=\"woocommerce-loop-product__title\"[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
CATEGORY_RE = re.compile(r"<span[^>]*class=\"ast-woo-product-category\"[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
SKU_RE = re.compile(r"data-product_sku=\"([^\"]*)\"", re.IGNORECASE)
IMAGE_SRC_RE = re.compile(r"<img[^>]+src=\"([^\"]+)\"", re.IGNORECASE)
IMAGE_ALT_RE = re.compile(r"<img[^>]+alt=\"([^\"]*)\"", re.IGNORECASE)
PRICE_RE = re.compile(r"<p[^>]*class=\"price\"[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
POSTED_IN_RE = re.compile(r"<span[^>]*class=\"posted_in\"[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
TAGGED_AS_RE = re.compile(r"<span[^>]*class=\"tagged_as\"[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
SKU_META_RE = re.compile(r"<span[^>]*class=\"sku\"[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
EXCERPT_RE = re.compile(r'"excerpt":"((?:\\.|[^"\\])*)"', re.DOTALL)
FEATURED_IMAGE_RE = re.compile(r'"featuredImage":"((?:\\.|[^"\\])*)"', re.DOTALL)
REFERENCE_TEXT_RE = re.compile(r"C[oó]digo\s+OE:\s*([^\n\r<|]+)", re.IGNORECASE)
BRAND_TEXT_RE = re.compile(r"Marca:\s*([^\n\r<|]+)", re.IGNORECASE)
APPLICATION_TEXT_RE = re.compile(r"Aplicaci[oó]n:\s*(.+)", re.IGNORECASE | re.DOTALL)
VEHICLE_TOKENS = (
    "chevrolet",
    "citroen",
    "fiat",
    "ford",
    "hyundai",
    "iveco",
    "jumpy",
    "jumper",
    "kia",
    "mazda",
    "mercedes",
    "nissan",
    "peugeot",
    "renault",
    "sprinter",
    "toyota",
    "transporter",
    "volkswagen",
    "amarok",
    "boxer",
    "ducato",
    "expert",
    "crafter",
)


@dataclass
class ListingEntry:
    page_number: int
    source_page_url: str
    product_url: str
    title: str | None
    category_name: str | None
    sku: str | None
    image_url: str | None
    image_alt: str | None


@dataclass
class DetailOutcome:
    record: ProductRecord
    warning: str | None = None
    failure: dict[str, str] | None = None


def log_progress(event: str, **payload: object) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def infer_match_type(
    title: str | None,
    category_name: str | None,
    description: str | None,
    reference: str | None,
) -> tuple[str, str, bool]:
    haystack = " ".join(filter(None, [title, category_name, description, reference])).lower()
    if any(token in haystack for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def page_number_from_url(url: str) -> int:
    match = re.search(r"/page/(\d+)/?", url)
    return int(match.group(1)) if match else 1


def normalize_page_url(url: str) -> str:
    normalized = canonical_url(url)
    if re.search(r"/page/1/?$", normalized):
        normalized = LISTING_ROOT_URL
    if normalized.rstrip("/") == LISTING_ROOT_URL.rstrip("/"):
        return LISTING_ROOT_URL
    return normalized if normalized.endswith("/") else normalized + "/"


def parse_visible_total(html: str) -> tuple[str | None, int | None]:
    match = RESULT_COUNT_RE.search(html)
    if not match:
        return None, None
    text = normalize_text(match.group(1))
    total_match = re.search(r"de\s+(\d+)\s+resultados", text, re.IGNORECASE)
    return text, (int(total_match.group(1)) if total_match else None)


def parse_category_text(block: str) -> str | None:
    match = CATEGORY_RE.search(block)
    if not match:
        return None
    anchors = re.findall(r">(.*?)</a>", match.group(1), re.IGNORECASE | re.DOTALL)
    parts = [normalize_text(anchor) for anchor in anchors if normalize_text(anchor)]
    if not parts:
        parts = [normalize_text(match.group(1))]
    return " / ".join(part for part in parts if part) or None


def parse_listing_entries(html: str, source_page_url: str) -> list[ListingEntry]:
    entries: list[ListingEntry] = []
    seen: set[str] = set()
    page_number = page_number_from_url(source_page_url)
    for block in LISTING_BLOCK_RE.findall(html):
        url_match = PRODUCT_URL_RE.search(block)
        if not url_match:
            continue
        product_url = canonical_url(url_match.group(0))
        if product_url in seen:
            continue
        seen.add(product_url)
        title_match = TITLE_RE.search(block)
        sku_match = SKU_RE.search(block)
        image_match = IMAGE_SRC_RE.search(block)
        image_alt_match = IMAGE_ALT_RE.search(block)
        entries.append(
            ListingEntry(
                page_number=page_number,
                source_page_url=source_page_url,
                product_url=product_url,
                title=normalize_text(title_match.group(1)) if title_match else None,
                category_name=parse_category_text(block),
                sku=normalize_text(sku_match.group(1)) if sku_match else None,
                image_url=canonical_url(urljoin(source_page_url, image_match.group(1))) if image_match else None,
                image_alt=normalize_text(image_alt_match.group(1)) if image_alt_match else None,
            )
        )
    return entries


def parse_pagination_links(html: str) -> list[str]:
    nav_match = PAGINATION_NAV_RE.search(html)
    if not nav_match:
        return []
    links: list[str] = []
    seen: set[str] = set()
    for raw_url in PAGE_LINK_RE.findall(nav_match.group(0)):
        normalized = normalize_page_url(raw_url)
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links


def next_listing_url(current_url: str) -> str:
    current_page = page_number_from_url(current_url)
    if current_page <= 1:
        return normalize_page_url(urljoin(LISTING_ROOT_URL, "page/2/"))
    return normalize_page_url(urljoin(LISTING_ROOT_URL, f"page/{current_page + 1}/"))


def parse_page_signature(entries: list[ListingEntry]) -> str:
    digest = hashlib.sha1()
    digest.update("\n".join(entry.product_url for entry in entries).encode("utf-8"))
    return digest.hexdigest()


def parse_json_string_field(html: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(html)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        return None


def strip_html_to_text(value: str | None) -> str | None:
    text = normalize_text(value)
    return text or None


def sanitize_brand(value: str | None) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    text = re.split(r"\b(?:c[oó]digo(?:\s+interno)?|aplicaci[oó]n)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = text.strip(" -:|/")
    parts = text.split()
    if len(parts) > 1:
        clean_parts: list[str] = []
        for part in parts:
            if any(char.isdigit() for char in part):
                break
            clean_parts.append(part)
        if clean_parts:
            text = " ".join(clean_parts)
    return text or None


def parse_excerpt_fields(excerpt_html: str | None) -> tuple[str | None, str | None, str | None]:
    if not excerpt_html:
        return None, None, None
    flattened = normalize_text(excerpt_html)
    reference_match = REFERENCE_TEXT_RE.search(flattened)
    brand_match = BRAND_TEXT_RE.search(flattened)
    application_match = APPLICATION_TEXT_RE.search(flattened)
    reference = normalize_text(reference_match.group(1)) if reference_match else None
    brand = sanitize_brand(brand_match.group(1)) if brand_match else None
    application = normalize_text(application_match.group(1)) if application_match else None
    return reference, brand, application


def parse_detail_categories(html: str) -> tuple[str | None, str | None]:
    posted_in_match = POSTED_IN_RE.search(html)
    tagged_in_match = TAGGED_AS_RE.search(html)
    posted_parts: list[str] = []
    tagged_parts: list[str] = []
    if posted_in_match:
        posted_parts = [normalize_text(value) for value in re.findall(r">(.*?)</a>", posted_in_match.group(1), re.IGNORECASE | re.DOTALL)]
        posted_parts = [value for value in posted_parts if value]
    if tagged_in_match:
        tagged_parts = [normalize_text(value) for value in re.findall(r">(.*?)</a>", tagged_in_match.group(1), re.IGNORECASE | re.DOTALL)]
        tagged_parts = [value for value in tagged_parts if value]
    category_name = posted_parts[0] if posted_parts else None
    subcategory_name = tagged_parts[0] if tagged_parts else None
    return category_name, subcategory_name


def parse_detail_price(html: str) -> str | None:
    match = PRICE_RE.search(html)
    if not match:
        return None
    text = normalize_text(match.group(1))
    return text or None


def build_listing_fallback(entry: ListingEntry, title: str | None = None, description: str | None = None) -> ProductRecord:
    final_title = title or entry.title or Path(urlparse(entry.product_url).path.rstrip("/")).name.replace("-", " ")
    match_type, confidence, manual = infer_match_type(final_title, entry.category_name, description, entry.sku)
    return ProductRecord(
        item_type="product",
        provider_type="product_catalog",
        product_name=final_title,
        product_url=entry.product_url,
        detail_url=entry.product_url,
        category_name=entry.category_name,
        brand=None,
        reference=entry.sku,
        sku=entry.sku,
        supplier_item_code=entry.sku,
        description=description,
        image_url=entry.image_url,
        source_page_url=entry.source_page_url,
        page_number=entry.page_number,
        match_type=match_type,
        match_confidence=confidence,
        requires_manual_confirmation=manual,
        searchable_tokens=build_searchable_tokens(final_title, entry.category_name, entry.sku, description),
    )


def parse_detail_record(entry: ListingEntry) -> DetailOutcome:
    try:
        final_url, raw, headers = fetch_url(entry.product_url)
        html = decode_html(raw, headers)
    except Exception as exc:  # noqa: BLE001
        record = build_listing_fallback(entry)
        return DetailOutcome(
            record=record,
            warning=f"Detalle no disponible para {entry.product_url}; se conserva fallback desde listing.",
            failure={"product_url": entry.product_url, "source_page_url": entry.source_page_url, "cause": f"fetch_error: {exc}"},
        )

    page_title = extract_page_title(html)
    meta_description = extract_meta_content(html, "description")
    meta_image = extract_meta_content(html, "og:image")
    json_ld_nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)]
    detail_records = product_from_json_ld(
        url=final_url,
        page_title=page_title,
        description=meta_description,
        image_url=meta_image,
        source_page_url=entry.source_page_url,
        json_ld_nodes=json_ld_nodes,
        infer_match_type=infer_match_type,
    )
    detail_record = detail_records[0] if detail_records else None

    excerpt_html = parse_json_string_field(html, EXCERPT_RE)
    featured_image = parse_json_string_field(html, FEATURED_IMAGE_RE)
    excerpt_description = strip_html_to_text(excerpt_html)
    excerpt_reference, excerpt_brand, excerpt_application = parse_excerpt_fields(excerpt_html)
    sku_meta_match = SKU_META_RE.search(html)
    sku_meta = normalize_text(sku_meta_match.group(1)) if sku_meta_match else None
    category_name, subcategory_name = parse_detail_categories(html)
    price_text = parse_detail_price(html)

    title = (
        (detail_record.product_name if detail_record else None)
        or page_title
        or entry.title
        or entry.image_alt
    )
    brand = (detail_record.brand if detail_record else None) or excerpt_brand
    reference = (detail_record.reference if detail_record else None) or excerpt_reference or entry.sku or sku_meta
    sku = (detail_record.sku if detail_record else None) or sku_meta or entry.sku or excerpt_reference
    description = (
        (detail_record.description if detail_record else None)
        or excerpt_description
        or meta_description
    )
    vehicle_scope = (
        (detail_record.vehicle_scope if detail_record else None)
        or excerpt_application
    )
    category_value = (
        (detail_record.category_name if detail_record else None)
        or category_name
        or entry.category_name
    )
    subcategory_value = (
        (detail_record.subcategory_name if detail_record else None)
        or subcategory_name
    )
    image_url = (
        (detail_record.image_url if detail_record else None)
        or featured_image
        or entry.image_url
        or meta_image
    )
    match_type, confidence, manual = infer_match_type(title, category_value, description, reference)
    searchable_tokens = build_searchable_tokens(
        title,
        brand,
        category_value,
        subcategory_value,
        description,
        reference,
        sku,
        vehicle_scope,
        price_text,
    )
    record = ProductRecord(
        item_type="product",
        provider_type="product_catalog",
        product_name=title,
        product_url=final_url,
        detail_url=final_url,
        category_name=category_value,
        subcategory_name=subcategory_value,
        brand=brand,
        reference=reference,
        sku=sku,
        supplier_item_code=sku,
        description=description,
        vehicle_scope=vehicle_scope,
        image_url=image_url,
        source_page_url=entry.source_page_url,
        page_number=entry.page_number,
        match_type=match_type,
        match_confidence=confidence,
        requires_manual_confirmation=manual,
        searchable_tokens=searchable_tokens,
    )

    warning: str | None = None
    failure: dict[str, str] | None = None
    if not detail_record and not excerpt_description:
        warning = f"Detalle de {entry.product_url} quedo limitado a campos del listing; la ficha publica no expuso descripcion util."
        failure = {
            "product_url": entry.product_url,
            "source_page_url": entry.source_page_url,
            "cause": "detail_parse_empty",
        }
    return DetailOutcome(record=record, warning=warning, failure=failure)


def crawl_listing() -> tuple[list[ListingEntry], list[dict[str, object]], list[str], int | None]:
    queue: list[str] = [LISTING_ROOT_URL]
    seen_pages: set[str] = set()
    entries_by_url: dict[str, ListingEntry] = {}
    page_evidence: list[dict[str, object]] = []
    notes: list[str] = []
    visible_total: int | None = None
    result_count_text: str | None = None
    signatures_seen: dict[str, str] = {}

    while queue:
        page_url = normalize_page_url(queue.pop(0))
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        try:
            final_url, raw, headers = fetch_url(page_url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"No se pudo abrir la pagina de listing {page_url}: {exc}")
            continue
        html = decode_html(raw, headers)
        final_page_url = normalize_page_url(final_url)
        result_count_text, current_visible_total = parse_visible_total(html)
        if current_visible_total and (visible_total is None or current_visible_total > visible_total):
            visible_total = current_visible_total

        listing_entries = parse_listing_entries(html, final_page_url)
        signature = parse_page_signature(listing_entries)
        duplicate_of = signatures_seen.get(signature)
        if not duplicate_of:
            signatures_seen[signature] = final_page_url
        else:
            notes.append(
                f"La pagina {final_page_url} repitio la misma grilla que {duplicate_of}; se conservo una sola evidencia para evitar duplicados."
            )

        for entry in listing_entries:
            entries_by_url.setdefault(entry.product_url, entry)

        page_evidence.append(
            {
                "page_number": page_number_from_url(final_page_url),
                "page_url": final_page_url,
                "result_count_text": result_count_text,
                "visible_products": len(listing_entries),
                "grid_signature": signature,
                "first_product_url": listing_entries[0].product_url if listing_entries else None,
                "last_product_url": listing_entries[-1].product_url if listing_entries else None,
                "duplicate_of": duplicate_of,
            }
        )
        log_progress(
            "importadoraeurobrasil_listing_page",
            page_number=page_number_from_url(final_page_url),
            visible_products=len(listing_entries),
            unique_products_so_far=len(entries_by_url),
            visible_total=visible_total,
        )

        discovered_links = parse_pagination_links(html)
        if len(listing_entries) >= PRODUCTS_PER_PAGE:
            discovered_links.append(next_listing_url(final_page_url))
        for candidate in discovered_links:
            normalized = normalize_page_url(candidate)
            if not same_host(normalized, urlparse(LISTING_ROOT_URL).netloc):
                continue
            if normalized in seen_pages or normalized in queue:
                continue
            queue.append(normalized)

        if visible_total and len(entries_by_url) >= visible_total:
            break

    page_evidence.sort(key=lambda item: int(item["page_number"]))
    return list(entries_by_url.values()), page_evidence, notes, visible_total


def collect_product_records(entries: list[ListingEntry]) -> tuple[list[ProductRecord], list[str], list[dict[str, str]]]:
    ordered_entries = sorted(entries, key=lambda item: (item.page_number, item.product_url))
    records: list[ProductRecord] = []
    notes: list[str] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        future_map = {executor.submit(parse_detail_record, entry): entry for entry in ordered_entries}
        for future in as_completed(future_map):
            outcome = future.result()
            records.append(outcome.record)
            if outcome.warning:
                notes.append(outcome.warning)
            if outcome.failure:
                failures.append(outcome.failure)
    records.sort(key=lambda record: (record.page_number, record.detail_url or record.product_url or ""))
    failures.sort(key=lambda item: item["product_url"])
    return records, notes, failures


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    metadata = load_json(metadata_path)
    snapshot_day = snapshot_date or date.today().isoformat()

    listing_entries, page_evidence, listing_notes, visible_total = crawl_listing()
    records, detail_notes, detail_failures = collect_product_records(listing_entries)
    final_count = len(records)

    notes = [AUTOS_ONLY_NOTE, MANUAL_NOTE]
    if visible_total:
        notes.append(f"Conteo visible del catalogo detectado en vivo: {visible_total} productos.")
    notes.append(f"Paginas de listing recorridas: {len(page_evidence)}.")
    notes.extend(listing_notes)
    notes.extend(detail_notes)
    if detail_failures:
        examples = ", ".join(item["product_url"] for item in detail_failures[:5])
        notes.append(
            f"Se requirio fallback o hubo parseo incompleto en {len(detail_failures)} fichas. Ejemplos: {examples}."
        )

    if visible_total and final_count < visible_total:
        missing = visible_total - final_count
        example_missing = ", ".join(entry.product_url for entry in sorted(listing_entries, key=lambda item: (item.page_number, item.product_url))[final_count:final_count + 5])
        notes.append(
            f"Resultado incompleto: faltan {missing} productos frente al conteo visible. Ejemplos no consolidados: {example_missing or 'sin ejemplo calculable'}."
        )

    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=records,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    extracted_path = write_snapshot_bundle(
        output_root=output_root,
        snapshot_date=snapshot_day,
        payload=payload,
        products=records,
    )
    snapshot_dir = extracted_path.parent
    (snapshot_dir / "listing_evidence.json").write_text(
        json.dumps(
            {
                "catalog_root_url": LISTING_ROOT_URL,
                "visible_total": visible_total,
                "pages": page_evidence,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (snapshot_dir / "detail_failures.json").write_text(
        json.dumps(detail_failures, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if visible_total and final_count < visible_total:
        missing = visible_total - final_count
        raise SystemExit(
            f"Extraccion incompleta para {PROVIDER_ID}: {final_count}/{visible_total} productos. Revisar {snapshot_dir / 'listing_evidence.json'} y {snapshot_dir / 'detail_failures.json'}. Faltan {missing}."
        )

    return extracted_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Live catalog extractor for {PROVIDER_ID}.")
    parser.add_argument("--snapshot-date", default=None)
    args = parser.parse_args(argv)
    path = run_extractor(snapshot_date=args.snapshot_date)
    print(json.dumps({"provider_id": PROVIDER_ID, "snapshot_path": str(path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



