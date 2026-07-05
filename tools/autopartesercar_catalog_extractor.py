#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path
import sys
from urllib.parse import urljoin, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.seeded_catalog_support import (  # noqa: E402
    AUTOS_ONLY_NOTE,
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
    build_searchable_tokens,
    canonical_url,
    decode_html,
    dedupe_records,
    default_category_like_url,
    default_product_like_url,
    entry_urls_from_snapshot,
    extract_links,
    extract_meta_content,
    extract_page_title,
    fetch_url,
    ignored_by_keywords,
    iter_json_ld_nodes,
    latest_snapshot_json,
    load_json,
    parse_category_record,
    parse_json_ld_blocks,
    parse_pdf_records,
    parse_product_fallback,
    product_from_json_ld,
    provider_paths,
    same_host,
    slug_to_words,
    url_matches_any,
    write_snapshot_bundle,
)

CONFIG = {
    "provider_id": "autopartesercar",
    "display_name": "Autopartes Ercar",
    "max_pages": 400,
    "max_products": 800,
    "category_only_mode": False,
    "prefer_vehicle_match": True,
    "collect_pdf_links": False,
    "image_catalog_only": False,
    "static_entry_urls": (),
    "allow_category_records": False,
    "extra_product_patterns": ("/product/",),
    "extra_category_patterns": (),
    "disallowed_url_patterns": (),
}
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
VEHICLE_TOKENS = (
    "chevrolet",
    "mazda",
    "renault",
    "kia",
    "hyundai",
    "nissan",
    "toyota",
    "ford",
    "volkswagen",
)
LISTING_SUMMARY_RE = re.compile(
    r"(?:Showing|Mostrando)\s+(\d+)\s*[–-]\s*(\d+)\s+(?:of|de)\s+(\d+)\s+(?:results|resultados)",
    re.I,
)

PROVIDER_ID = CONFIG["provider_id"]
DISPLAY_NAME = CONFIG["display_name"]
MAX_PAGES = CONFIG["max_pages"]
MAX_PRODUCTS = CONFIG["max_products"]
CATEGORY_ONLY_MODE = CONFIG["category_only_mode"]
PREFER_VEHICLE_MATCH = CONFIG["prefer_vehicle_match"]
COLLECT_PDF_LINKS = CONFIG["collect_pdf_links"]
IMAGE_CATALOG_ONLY = CONFIG["image_catalog_only"]
ALLOW_CATEGORY_RECORDS = CONFIG["allow_category_records"]
STATIC_ENTRY_URLS = CONFIG["static_entry_urls"]
EXTRA_PRODUCT_PATTERNS = CONFIG["extra_product_patterns"]
EXTRA_CATEGORY_PATTERNS = CONFIG["extra_category_patterns"]
DISALLOWED_URL_PATTERNS = CONFIG["disallowed_url_patterns"]


def infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, category_name, description])).lower()
    if CATEGORY_ONLY_MODE:
        return "category_only", "medium", True
    if PREFER_VEHICLE_MATCH and any(token in allowed_text for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", True
    if reference and not CATEGORY_ONLY_MODE:
        return ("vehicle_compatible" if PREFER_VEHICLE_MATCH else "category_only"), "medium", True
    return "category_only", "medium", True


def ignored_url(url: str) -> bool:
    return url_matches_any(url, DISALLOWED_URL_PATTERNS) or ignored_by_keywords(url, EXCLUDE_KEYWORDS)


def product_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    return default_product_like_url(url) or url_matches_any(url, EXTRA_PRODUCT_PATTERNS)


def category_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    return default_category_like_url(url) or url_matches_any(url, EXTRA_CATEGORY_PATTERNS)


def listing_like_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(hint in path for hint in ("/tienda/", "/product-category/", "/categoria-producto/", "/category/"))


def build_listing_page_url(page_url: str, page_number: int) -> str:
    parsed = urlparse(page_url)
    path = parsed.path or "/"
    if "/page/" in path:
        base_path = re.sub(r"/page/\d+/?$", "/", path)
    else:
        base_path = path if path.endswith("/") else f"{path}/"
    if page_number <= 1:
        new_path = base_path
    else:
        new_path = f"{base_path.rstrip('/')}/page/{page_number}/"
    return parsed._replace(path=new_path, query="").geturl()


def collect_listing_surface_urls(html: str, page_url: str) -> tuple[set[str], set[str], tuple[int | None, int | None, int | None]]:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    start = end = total = None
    match = LISTING_SUMMARY_RE.search(text)
    if match:
        start, end, total = int(match.group(1)), int(match.group(2)), int(match.group(3))

    product_urls: set[str] = set()
    listing_urls: set[str] = set()
    host = urlparse(page_url).netloc

    hrefs = re.findall(r"href=[\"']([^\"']+)[\"']", html, flags=re.I)
    for href in hrefs:
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = canonical_url(urljoin(page_url, href))
        if not same_host(absolute, host):
            continue
        parsed_absolute = urlparse(absolute)
        has_pagination_query = re.search(r"(?:^|[?&])(page|paged)=\d+", parsed_absolute.query)
        if product_like_url(absolute):
            product_urls.add(canonical_url(absolute))
            continue
        if category_like_url(absolute):
            listing_urls.add(canonical_url(absolute))
            continue
        if listing_like_url(absolute):
            if parsed_absolute.query and not has_pagination_query:
                continue
            listing_urls.add(canonical_url(absolute))
            continue
        if "/page/" in parsed_absolute.path or has_pagination_query:
            listing_urls.add(canonical_url(absolute))

    if total and start and end:
        per_page = max(1, end - start + 1)
        max_page = max(1, math.ceil(total / per_page))
        for page_number in range(1, max_page + 1):
            listing_urls.add(build_listing_page_url(page_url, page_number))

    return product_urls, listing_urls, (start, end, total)


def crawl_provider(
    metadata: dict[str, object],
    seed_snapshot: dict[str, object] | None,
    output_root: Path | None = None,
    snapshot_day: str | None = None,
) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    entry_urls = [str(metadata.get("catalog_root_url") or metadata.get("website") or "")]
    entry_urls.extend(STATIC_ENTRY_URLS)
    if seed_snapshot:
        entry_urls.extend(entry_urls_from_snapshot(seed_snapshot))

    queue: list[tuple[str, str]] = []
    seen_queue: set[str] = set()
    for url in entry_urls:
        if not url or not url.startswith("http"):
            continue
        normalized = canonical_url(url)
        if ignored_url(normalized):
            continue
        if normalized not in seen_queue and same_host(normalized, host):
            queue.append((normalized, normalized))
            seen_queue.add(normalized)

    visited: set[str] = set()
    discovered_listing_pages: set[str] = set()
    discovered_product_sources: dict[str, str] = {}
    listing_warnings: list[str] = [AUTOS_ONLY_NOTE]
    root_listing_url = canonical_url(str(metadata.get("catalog_root_url") or metadata.get("website") or ""))
    last_discovery_snapshot_count = 0

    def persist_discovery_snapshot(reason: str) -> None:
        if output_root is None or snapshot_day is None or not discovered_product_sources:
            return
        discovery_records: list[ProductRecord] = [
            ProductRecord(
                item_type="product",
                provider_type="category_only",
                title=slug_to_words(Path(urlparse(product_url).path).stem) or slug_to_words(Path(urlparse(product_url).path).name) or DISPLAY_NAME,
                product_name=slug_to_words(Path(urlparse(product_url).path).stem) or slug_to_words(Path(urlparse(product_url).path).name) or DISPLAY_NAME,
                detail_url=product_url,
                product_url=product_url,
                category_name=slug_to_words(Path(urlparse(source_page_url).path).name) or "Catalogo publico",
                description="Producto descubierto desde el catalogo publico; pendiente de enriquecimiento detallado.",
                source_page_url=source_page_url,
                page_number=1,
                match_type="manual_confirmation_required",
                match_confidence="low",
                requires_manual_confirmation=True,
                searchable_tokens=build_searchable_tokens(
                    DISPLAY_NAME,
                    slug_to_words(Path(urlparse(product_url).path).stem),
                    slug_to_words(Path(urlparse(product_url).path).name),
                    "catalogo",
                    "publico",
                ),
            )
            for product_url, source_page_url in discovered_product_sources.items()
        ]
        discovery_records = dedupe_records(discovery_records, EXCLUDE_KEYWORDS)
        if not discovery_records:
            return
        interim_payload = build_payload(
            provider_id=PROVIDER_ID,
            provider_name=DISPLAY_NAME,
            metadata=metadata,
            products=discovery_records,
            notes=list(dict.fromkeys(listing_warnings + [AUTOS_ONLY_NOTE, MANUAL_NOTE, f"Listing pages crawled: {len(discovered_listing_pages)}", f"Product pages discovered: {len(discovered_product_sources)}", f"Discovery snapshot: {reason}"])),
            snapshot_date=snapshot_day,
        )
        write_snapshot_bundle(
            output_root=output_root,
            snapshot_date=snapshot_day,
            payload=interim_payload,
            products=discovery_records,
        )

    while queue and len(visited) < MAX_PAGES:
        url, source_page_url = queue.pop(0)
        if url in visited or ignored_url(url):
            continue
        visited.add(url)
        try:
            final_url, raw, headers = fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            listing_warnings.append(f"Fetch warning for {url}: {exc}")
            continue

        if ignored_url(final_url):
            continue

        content_type = headers.get("content-type", "").lower()
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            continue

        html = decode_html(raw, headers)

        if listing_like_url(final_url) and not product_like_url(final_url):
            listing_product_urls, listing_urls, summary = collect_listing_surface_urls(html, final_url)
            if summary[2] and canonical_url(final_url) not in discovered_listing_pages:
                listing_warnings.append(f"Listing summary for {final_url}: {summary[0]}-{summary[1]} of {summary[2]}")
            discovered_listing_pages.add(canonical_url(final_url))
            if len(discovered_listing_pages) == 1 or len(discovered_listing_pages) % 5 == 0:
                print(
                    json.dumps(
                        {
                            "event": "autopartesercar_listing_progress",
                            "visited": len(visited),
                            "listing_pages": len(discovered_listing_pages),
                            "product_sources": len(discovered_product_sources),
                            "current_url": final_url,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            for link in sorted(listing_product_urls):
                normalized_link = canonical_url(link)
                if normalized_link in discovered_product_sources:
                    continue
                if not same_host(normalized_link, host) or ignored_url(normalized_link):
                    continue
                discovered_product_sources[normalized_link] = final_url
            if output_root is not None and snapshot_day is not None and discovered_product_sources:
                current_discovery_count = len(discovered_product_sources)
                if current_discovery_count != last_discovery_snapshot_count:
                    persist_discovery_snapshot(f"listing page {len(discovered_listing_pages)}")
                    last_discovery_snapshot_count = current_discovery_count
            for link in sorted(listing_urls):
                normalized_link = canonical_url(link)
                if normalized_link in visited or normalized_link in seen_queue:
                    continue
                if not same_host(normalized_link, host) or ignored_url(normalized_link):
                    continue
                parsed_link = urlparse(normalized_link)
                is_pagination_link = "/page/" in parsed_link.path or re.search(r"(?:^|[?&])(page|paged)=\d+", parsed_link.query)
                is_category_link = category_like_url(normalized_link) or listing_like_url(normalized_link)
                if parsed_link.query and not is_pagination_link and not is_category_link:
                    continue
                if canonical_url(final_url) != root_listing_url and not (is_pagination_link or is_category_link):
                    continue
                queue.append((normalized_link, final_url))
                seen_queue.add(normalized_link)
            continue

        if product_like_url(final_url):
            discovered_product_sources.setdefault(canonical_url(final_url), source_page_url)
            continue

    discovery_records: list[ProductRecord] = [
        ProductRecord(
            item_type="product",
            provider_type="category_only",
            title=slug_to_words(Path(urlparse(product_url).path).stem) or slug_to_words(Path(urlparse(product_url).path).name) or DISPLAY_NAME,
            product_name=slug_to_words(Path(urlparse(product_url).path).stem) or slug_to_words(Path(urlparse(product_url).path).name) or DISPLAY_NAME,
            detail_url=product_url,
            product_url=product_url,
            category_name=slug_to_words(Path(urlparse(source_page_url).path).name) or "Catalogo publico",
            description="Producto descubierto desde el catalogo publico; pendiente de enriquecimiento detallado.",
            source_page_url=source_page_url,
            page_number=1,
            match_type="manual_confirmation_required",
            match_confidence="low",
            requires_manual_confirmation=True,
            searchable_tokens=build_searchable_tokens(
                DISPLAY_NAME,
                slug_to_words(Path(urlparse(product_url).path).stem),
                slug_to_words(Path(urlparse(product_url).path).name),
                "catalogo",
                "publico",
            ),
        )
        for product_url, source_page_url in discovered_product_sources.items()
    ]
    discovery_records = dedupe_records(discovery_records, EXCLUDE_KEYWORDS)
    if output_root is not None and snapshot_day is not None and discovery_records:
        interim_payload = build_payload(
            provider_id=PROVIDER_ID,
            provider_name=DISPLAY_NAME,
            metadata=metadata,
            products=discovery_records,
            notes=notes + ["Interim discovery snapshot written before detail parsing."],
            snapshot_date=snapshot_day,
        )
        write_snapshot_bundle(
            output_root=output_root,
            snapshot_date=snapshot_day,
            payload=interim_payload,
            products=discovery_records,
        )
    def parse_product_detail(product_url: str, source_page_url: str) -> tuple[list[ProductRecord], str | None]:
        try:
            final_url, raw, headers = fetch_url(product_url)
        except Exception as exc:  # noqa: BLE001
            return [], f"Fetch warning for {product_url}: {exc}"

        if ignored_url(final_url):
            return [], None

        content_type = headers.get("content-type", "").lower()
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            if COLLECT_PDF_LINKS:
                return parse_pdf_records(f'<a href="{final_url}">{DISPLAY_NAME}</a>', final_url, source_page_url), None
            return [], None

        html = decode_html(raw, headers)
        page_title = extract_page_title(html)
        meta_description = extract_meta_content(html, "description")
        meta_image = extract_meta_content(html, "og:image")
        json_ld_nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)]
        product_records = product_from_json_ld(
            url=final_url,
            page_title=page_title,
            description=meta_description,
            image_url=meta_image,
            source_page_url=source_page_url,
            json_ld_nodes=json_ld_nodes,
            infer_match_type=infer_match_type,
        )

        if not product_records:
            fallback = parse_product_fallback(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                category_only_mode=CATEGORY_ONLY_MODE,
                infer_match_type=infer_match_type,
            )
            if fallback:
                product_records = [fallback]

        if not product_records and ALLOW_CATEGORY_RECORDS and (category_like_url(final_url) or final_url in entry_urls):
            category_record = parse_category_record(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                exclude_keywords=EXCLUDE_KEYWORDS,
                match_type="category_only" if CATEGORY_ONLY_MODE else "manual_confirmation_required",
            )
            if category_record:
                product_records = [category_record]

        return product_records, None

    records: list[ProductRecord] = []
    workers = min(8, max(1, len(discovered_product_sources)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(parse_product_detail, product_url, source_url): product_url
            for product_url, source_url in discovered_product_sources.items()
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            product_records, warning = future.result()
            if warning:
                listing_warnings.append(warning)
            if product_records:
                records.extend(product_records)
            if index == 1 or index % 25 == 0 or index == len(future_map):
                print(
                    json.dumps(
                        {
                            "event": "autopartesercar_progress",
                            "attempted": index,
                            "parsed": len(records),
                            "parsed_urls": len([record for record in records if getattr(record, "detail_url", None)]),
                            "failed": len([item for item in listing_warnings if item.startswith("Fetch warning")]),
                            "listing_pages": len(discovered_listing_pages),
                            "product_urls": len(discovered_product_sources),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    if IMAGE_CATALOG_ONLY and not records and entry_urls:
        records.append(
            ProductRecord(
                item_type="category",
                provider_type="category_only",
                title=DISPLAY_NAME,
                detail_url=entry_urls[0],
                category_name=DISPLAY_NAME,
                description="Catalogo visual publico; la extraccion viva se mantiene como verificacion manual.",
                source_page_url=entry_urls[0],
                match_type="manual_confirmation_required",
                match_confidence="low",
                requires_manual_confirmation=True,
                searchable_tokens=[DISPLAY_NAME.lower(), "catalogo", "visual"],
            )
        )

    notes = list(dict.fromkeys(listing_warnings + [MANUAL_NOTE]))
    notes.insert(1, f"Listing pages crawled: {len(discovered_listing_pages)}")
    notes.insert(2, f"Product pages discovered: {len(discovered_product_sources)}")

    return dedupe_records(records, EXCLUDE_KEYWORDS), notes


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes = crawl_provider(metadata, seed_snapshot, output_root=output_root, snapshot_day=snapshot_day)
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=products,
        notes=notes,
        snapshot_date=snapshot_day,
    )
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














