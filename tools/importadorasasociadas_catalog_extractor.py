#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
from datetime import date
from pathlib import Path
import sys
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

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
    dedupe_records,
    extract_links,
    fetch_url,
    latest_snapshot_json,
    load_json,
    normalize_text,
    provider_paths,
    same_host,
    write_snapshot_bundle,
)

PROVIDER_ID = "importadorasasociadas"
DISPLAY_NAME = "Importadoras Asociadas"
VTEX_ENDPOINT = "https://www.importadorasasociadas.com/_v/segment/graphql/v1"
VTEX_BINDING_ID = "a1a0a157-ddec-4b4c-85cc-04c7d3c71e25"
VTEX_PERSISTED_HASH = "b398fc0a2fd04ea5d4f7a94c732c10fb1bf64f8f9a2b31c92aee6a5e796457c9"
VTEX_PAGE_SIZE = 48
MAX_CATEGORY_SURFACES = 500
MAX_PRODUCTS = 250000
EXCLUDE_KEYWORDS = (
    "moto",
    "motoc",
    "camion",
    "camiones",
    "bus",
    "buses",
    "tracto",
    "npr",
    "diesel",
    "agricola",
    "industrial",
)
DISALLOWED_URL_PATTERNS = (
    "/login",
    "/account",
    "/_secure",
    "/checkout",
    "/cart",
    "/institucional",
)
DEFAULT_CATEGORY_ENTRY_URLS = (
    "https://www.importadorasasociadas.com/categorias/aceites",
    "https://www.importadorasasociadas.com/categorias/motor",
    "https://www.importadorasasociadas.com/categorias/direccion-y-suspension",
    "https://www.importadorasasociadas.com/categorias/electricos",
    "https://www.importadorasasociadas.com/categorias/refrigeracion",
    "https://www.importadorasasociadas.com/categorias/carroceria",
    "https://www.importadorasasociadas.com/categorias/frenado",
    "https://www.importadorasasociadas.com/categorias/accesorios",
    "https://www.importadorasasociadas.com/categorias/clutch",
    "https://www.importadorasasociadas.com/categorias/filtracion",
    "https://www.importadorasasociadas.com/categorias/iluminacion",
    "https://www.importadorasasociadas.com/categorias/correas",
    "https://www.importadorasasociadas.com/categorias/baterias",
)


def first_text(value: object) -> str | None:
    if isinstance(value, str):
        normalized = normalize_text(value)
        return normalized or None
    if isinstance(value, list):
        for item in value:
            text = first_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("name", "text", "value", "Value", "content", "label", "@id"):
            if key in value:
                text = first_text(value.get(key))
                if text:
                    return text
    return None


def first_image_url(value: object) -> str | None:
    if isinstance(value, str):
        normalized = normalize_text(value)
        return normalized if normalized.startswith("http") else None
    if isinstance(value, list):
        for item in value:
            image_url = first_image_url(item)
            if image_url:
                return image_url
    if isinstance(value, dict):
        for key in ("contentUrl", "url", "@id", "imageUrl"):
            image_url = first_image_url(value.get(key))
            if image_url:
                return image_url
    return None


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    if any(pattern in lowered for pattern in DISALLOWED_URL_PATTERNS):
        return True
    return any(keyword in lowered for keyword in EXCLUDE_KEYWORDS)


def category_path_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return None
    if "categorias" not in path.lower():
        return None
    return path


def selected_facets_from_query_path(query_path: str) -> list[dict[str, str]]:
    facets: list[dict[str, str]] = []
    for segment in [part for part in query_path.split("/") if part]:
        facets.append({"key": "c", "value": segment})
    return facets


def graphql_url(query_path: str, offset: int, page_size: int = VTEX_PAGE_SIZE) -> str:
    segments = [part for part in query_path.split("/") if part]
    payload = {
        "skusFilter": "ALL_AVAILABLE",
        "simulationBehavior": "default",
        "installmentCriteria": "MAX_WITHOUT_INTEREST",
        "productOriginVtex": False,
        "map": ",".join(["c"] * len(segments)),
        "query": query_path,
        "orderBy": "OrderByScoreDESC",
        "from": offset,
        "to": offset + page_size - 1,
        "selectedFacets": selected_facets_from_query_path(query_path),
        "operator": "and",
        "fuzzy": "0",
        "searchState": None,
        "hideUnavailableItems": True,
        "facetsBehavior": "Static",
        "categoryTreeBehavior": "default",
        "withFacets": False,
    }
    extensions = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": VTEX_PERSISTED_HASH,
            "sender": "vtex.store-resources@0.x",
            "provider": "vtex.search-graphql@0.x",
        },
        "variables": base64.b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).decode("ascii"),
    }
    query_params = {
        "workspace": "master",
        "maxAge": "short",
        "appsEtag": "remove",
        "domain": "store",
        "locale": "es-CO",
        "__bindingId": VTEX_BINDING_ID,
        "operationName": "productSearchV3",
        "variables": "{}",
        "extensions": json.dumps(extensions, separators=(",", ":"), ensure_ascii=False),
    }
    return f"{VTEX_ENDPOINT}?{urlencode(query_params, quote_via=quote)}"


def fetch_graphql_payload(query_path: str, offset: int, page_size: int = VTEX_PAGE_SIZE) -> dict[str, object]:
    request = Request(
        graphql_url(query_path, offset, page_size),
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.importadorasasociadas.com/",
            "Origin": "https://www.importadorasasociadas.com",
        },
    )
    with urlopen(request, timeout=60) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip

        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8", errors="replace"))


def html_to_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = normalize_text(text)
    return text or None


def product_categories(product: dict[str, object]) -> tuple[str | None, str | None]:
    candidates: list[list[str]] = []
    for raw_category in product.get("categories", []) or []:
        if not isinstance(raw_category, str):
            continue
        cleaned = raw_category.strip("/")
        if not cleaned.lower().startswith("categorias/"):
            continue
        tail = cleaned.split("/", 1)[1] if "/" in cleaned else ""
        parts = [normalize_text(part.replace("-", " ")) for part in tail.split("/") if normalize_text(part.replace("-", " "))]
        if parts:
            candidates.append(parts)
    if not candidates:
        return None, None
    best = max(candidates, key=len)
    if len(best) == 1:
        return best[0], None
    return best[-2], best[-1]


def walk_text_values(value: object) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        text = normalize_text(value)
        if text:
            values.append(text)
    elif isinstance(value, dict):
        for key in ("name", "originalName", "text", "value", "Value", "label"):
            values.extend(walk_text_values(value.get(key)))
        for key in ("values", "specifications", "items"):
            if key in value:
                values.extend(walk_text_values(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            values.extend(walk_text_values(item))
    return values


def collect_specification_text(product: dict[str, object]) -> str:
    fragments: list[str] = []
    for group in product.get("specificationGroups", []) or []:
        if not isinstance(group, dict):
            continue
        group_name = first_text(group.get("name"))
        for spec in group.get("specifications", []) or []:
            if not isinstance(spec, dict):
                continue
            spec_name = first_text(spec.get("name"))
            values = []
            for value in spec.get("values", []) or []:
                text = first_text(value)
                if text:
                    values.append(text)
            if spec_name or values:
                fragments.append(" ".join(part for part in [group_name, spec_name, " ".join(values)] if part))
    for key in ("skuSpecifications", "selectedProperties", "properties"):
        fragments.append(" ".join(text for text in walk_text_values(product.get(key, [])) if text))
    return normalize_text(" ".join(fragment for fragment in fragments if fragment))


def product_image_url(product: dict[str, object]) -> str | None:
    for item in product.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        for image in item.get("images", []) or []:
            image_url = first_image_url(image)
            if image_url:
                return image_url
    return first_image_url(product.get("image"))


def product_reference(product: dict[str, object]) -> str | None:
    reference = first_text(product.get("productReference"))
    if reference:
        return reference
    for item in product.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        for ref in item.get("referenceId", []) or []:
            if isinstance(ref, dict):
                text = first_text(ref.get("Value")) or first_text(ref.get("value"))
                if text:
                    return text
        text = first_text(item.get("ean"))
        if text:
            return text
    return None


def product_sku(product: dict[str, object]) -> str | None:
    for item in product.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        text = first_text(item.get("itemId"))
        if text:
            return text
    return first_text(product.get("productId"))


def infer_match_type(
    title: str | None,
    category_name: str | None,
    description: str | None,
    reference: str | None,
    compatibility_text: str | None,
) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, category_name, description, compatibility_text])).lower()
    if reference:
        return "exact_reference", "high", False
    if any(token in allowed_text for token in ("marca de vehículo", "familia", "modelo", "cilindraje", "compatibilidad")):
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def product_record_from_search(
    *,
    product: dict[str, object],
    base_url: str,
    source_page_url: str,
    query_path: str,
    page_number: int,
) -> ProductRecord | None:
    product_name = first_text(product.get("productName"))
    if not product_name:
        return None
    detail_link = first_text(product.get("link")) or ""
    detail_url = canonical_url(urljoin(base_url, detail_link)) if detail_link else None
    if not detail_url or ignored_url(detail_url):
        return None

    brand = first_text(product.get("brand"))
    reference = product_reference(product)
    sku = product_sku(product)
    description = html_to_text(product.get("description"))
    image_url = product_image_url(product)
    category_name, subcategory_name = product_categories(product)
    compatibility_text = collect_specification_text(product)
    vehicle_scope = "Autos"
    match_type, confidence, manual = infer_match_type(product_name, category_name, description, reference, compatibility_text)
    tokens = build_searchable_tokens(
        product_name,
        brand,
        category_name,
        subcategory_name,
        description,
        reference,
        sku,
        vehicle_scope,
        compatibility_text,
        query_path,
    )
    return ProductRecord(
        item_type="product",
        provider_type="product_catalog",
        product_name=product_name,
        product_url=detail_url,
        detail_url=detail_url,
        category_name=category_name,
        subcategory_name=subcategory_name,
        brand=brand,
        reference=reference,
        sku=sku,
        supplier_item_code=sku or reference,
        description=description,
        vehicle_scope=vehicle_scope,
        image_url=image_url,
        source_page_url=source_page_url,
        page_number=page_number,
        match_type=match_type,
        match_confidence=confidence,
        requires_manual_confirmation=manual,
        searchable_tokens=tokens,
    )


def fetch_category_html(url: str) -> tuple[str, str] | None:
    try:
        final_url, raw, headers = fetch_url(url)
    except Exception:
        return None
    return final_url, decode_html(raw, headers)


def discover_category_links(html: str, base_url: str, host: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for link in extract_links(html, base_url):
        parsed = urlparse(link)
        if parsed.netloc.lower() != host:
            continue
        if ignored_url(link):
            continue
        if "/categorias/" not in parsed.path.lower():
            continue
        if parsed.query and "page=" not in parsed.query.lower():
            continue
        normalized = canonical_url(link)
        if normalized not in seen:
            links.append(normalized)
            seen.add(normalized)
    return links


def seed_category_urls(metadata: dict[str, object]) -> list[str]:
    urls: list[str] = []
    catalog = metadata.get("catalog")
    if isinstance(catalog, dict):
        for value in catalog.get("entry_urls", []) or []:
            if isinstance(value, str):
                urls.append(value)
    selectors = metadata.get("selectors")
    if isinstance(selectors, dict):
        for key in ("category_entry_hint", "category_entry_urls", "autos_category_root"):
            value = selectors.get(key)
            if isinstance(value, str):
                urls.append(value)
            elif isinstance(value, list):
                urls.extend([item for item in value if isinstance(item, str)])
    urls.extend(list(DEFAULT_CATEGORY_ENTRY_URLS))
    urls.append(str(metadata.get("catalog_root_url") or metadata.get("website") or ""))
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or not url.startswith("http"):
            continue
        normalized = canonical_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def crawl_category_surface(
    *,
    url: str,
    host: str,
    seen_surfaces: set[str],
    queue: list[str],
    base_root: str,
) -> tuple[list[ProductRecord], list[str], dict[str, object]]:
    coverage: dict[str, object] = {
        "surface_url": url,
        "query_path": category_path_from_url(url),
        "records_filtered": 0,
        "pages_requested": 0,
        "products_collected": 0,
        "discovered_subcategories": [],
    }
    records: list[ProductRecord] = []
    notes: list[str] = []
    html_result = fetch_category_html(url)
    if html_result:
        final_url, html = html_result
        coverage["surface_url"] = final_url
        discovered = discover_category_links(html, final_url, host)
        if discovered:
            coverage["discovered_subcategories"] = discovered
            for link in discovered:
                if link not in seen_surfaces and link not in queue:
                    queue.append(link)
        if html:
            notes.append(f"Categoria HTML revisada: {final_url}")

    query_path = category_path_from_url(url)
    if not query_path:
        notes.append(f"Surface skipped without category path: {url}")
        return records, notes, coverage

    offset = 0
    page_number = 1
    total_filtered: int | None = None
    while len(records) < MAX_PRODUCTS and page_number <= MAX_CATEGORY_SURFACES:
        try:
            payload = fetch_graphql_payload(query_path, offset, VTEX_PAGE_SIZE)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"VTEX fetch warning for {url} offset {offset}: {exc}")
            break

        search_data = (payload.get("data") or {}).get("productSearch") or {}
        products = search_data.get("products") or []
        if total_filtered is None:
            total_filtered = int(search_data.get("recordsFiltered") or 0)
            coverage["records_filtered"] = total_filtered
        if not isinstance(products, list) or not products:
            break

        coverage["pages_requested"] = int(coverage["pages_requested"]) + 1
        for product in products:
            if not isinstance(product, dict):
                continue
            record = product_record_from_search(
                product=product,
                base_url=base_root,
                source_page_url=url,
                query_path=query_path,
                page_number=page_number,
            )
            if record:
                records.append(record)
                coverage["products_collected"] = int(coverage["products_collected"]) + 1

        offset += VTEX_PAGE_SIZE
        page_number += 1
        if total_filtered is not None and offset >= total_filtered:
            break
        if len(products) < VTEX_PAGE_SIZE:
            break

    return records, notes, coverage


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str], dict[str, object]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    base_root = str(metadata.get("website") or metadata.get("catalog_root_url") or "")
    queue = seed_category_urls(metadata)
    if seed_snapshot:
        for candidate in seed_snapshot.get("products", []) or []:
            if not isinstance(candidate, dict):
                continue
            for field_name in ("source_page_url", "product_url", "detail_url", "category_url", "url"):
                value = candidate.get(field_name)
                if isinstance(value, str) and value.startswith("http"):
                    normalized = canonical_url(value)
                    if normalized not in queue and same_host(normalized, host):
                        if "/categorias/" in urlparse(normalized).path.lower():
                            queue.append(normalized)

    seen_surfaces: set[str] = set()
    all_records: list[ProductRecord] = []
    notes = [
        AUTOS_ONLY_NOTE,
        "VTEX productSearchV3 es la fuente principal de descubrimiento; los detalles de producto y la imagen ya vienen en la respuesta del catálogo.",
    ]
    coverage: dict[str, object] = {
        "api": {
            "endpoint": VTEX_ENDPOINT,
            "operation_name": "productSearchV3",
            "page_size": VTEX_PAGE_SIZE,
            "binding_id": VTEX_BINDING_ID,
        },
        "category_surfaces": [],
        "discovered_surface_count": 0,
    }

    while queue and len(seen_surfaces) < MAX_CATEGORY_SURFACES and len(all_records) < MAX_PRODUCTS:
        url = queue.pop(0)
        if url in seen_surfaces or ignored_url(url):
            continue
        if "/categorias/" not in urlparse(url).path.lower():
            continue
        seen_surfaces.add(url)
        records, surface_notes, surface_coverage = crawl_category_surface(
            url=url,
            host=host,
            seen_surfaces=seen_surfaces,
            queue=queue,
            base_root=base_root,
        )
        all_records.extend(records)
        notes.extend(surface_notes)
        if surface_coverage.get("query_path"):
            coverage["category_surfaces"].append(surface_coverage)

    coverage["discovered_surface_count"] = len(seen_surfaces)
    coverage["record_count_before_dedupe"] = len(all_records)
    deduped = dedupe_records(all_records, EXCLUDE_KEYWORDS)
    coverage["record_count_after_dedupe"] = len(deduped)
    notes.append(f"Surface count crawled: {len(seen_surfaces)}")
    notes.append(f"Records before dedupe: {len(all_records)}")
    notes.append(f"Records after dedupe: {len(deduped)}")
    notes.append(MANUAL_NOTE)
    return deduped, list(dict.fromkeys(notes)), coverage


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes, coverage = crawl_provider(metadata, seed_snapshot)
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=products,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    payload["catalog_coverage"] = coverage
    return write_snapshot_bundle(output_root=output_root, snapshot_date=snapshot_day, payload=payload, products=products)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Live catalog extractor for {PROVIDER_ID}.")
    parser.add_argument("--snapshot-date", default=None)
    args = parser.parse_args(argv)
    path = run_extractor(snapshot_date=args.snapshot_date)
    print(json.dumps({"provider_id": PROVIDER_ID, "snapshot_path": str(path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
