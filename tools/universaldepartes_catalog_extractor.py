#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
import sys
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.seeded_catalog_support import (
    AUTOS_ONLY_NOTE,
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
    canonical_url,
    decode_html,
    dedupe_records,
    entry_urls_from_snapshot,
    extract_links,
    extract_meta_content,
    extract_page_title,
    fetch_url,
    ignored_by_keywords,
    iter_json_ld_nodes,
    latest_snapshot_json,
    load_json,
    parse_json_ld_blocks,
    parse_product_fallback,
    product_from_json_ld,
    provider_paths,
    same_host,
    write_snapshot_bundle,
)

PROVIDER_ID = "universaldepartes"
DISPLAY_NAME = "Universal de Partes"
MAX_CATEGORY_PAGES = 4
MAX_PRODUCTS = 48
ENTRY_HINTS = (
    "https://www.universaldepartes.co/category/all-products",
    "https://www.universaldepartes.co/category/all-products?page=2",
)
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


def infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    text = " ".join(filter(None, [title, category_name, description])).lower()
    vehicle_tokens = ("chevrolet", "mazda", "renault", "kia", "hyundai", "nissan", "toyota", "ford", "volkswagen")
    if any(token in text for token in vehicle_tokens):
        return "vehicle_compatible", "medium", True
    if reference:
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def ignored_url(url: str) -> bool:
    return ignored_by_keywords(url.lower(), EXCLUDE_KEYWORDS)


def product_like_url(url: str) -> bool:
    parsed = urlparse(url)
    return "/product-page/" in parsed.path and not ignored_url(url)


def category_like_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path.rstrip("/") == "/category/all-products" and not ignored_url(url)


def parse_product_page(url: str, html: str, source_page_url: str) -> list[ProductRecord]:
    page_title = extract_page_title(html)
    meta_description = extract_meta_content(html, "description")
    meta_image = extract_meta_content(html, "og:image")
    nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)]
    records = product_from_json_ld(
        url=url,
        page_title=page_title,
        description=meta_description,
        image_url=meta_image,
        source_page_url=source_page_url,
        json_ld_nodes=nodes,
        infer_match_type=infer_match_type,
    )
    if not records:
        fallback = parse_product_fallback(
            url=url,
            html=html,
            source_page_url=source_page_url,
            category_only_mode=False,
            infer_match_type=infer_match_type,
        )
        records = [fallback] if fallback else []
    for record in records:
        record.provider_type = "product_catalog_partial"
        record.vehicle_scope = record.vehicle_scope or "Autos"
        record.requires_manual_confirmation = True
        if not record.category_name:
            record.category_name = "Todos los productos"
    return records


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    entry_urls = [str(metadata.get("catalog_root_url") or metadata.get("website") or "")]
    entry_urls.extend(ENTRY_HINTS)
    if seed_snapshot:
        entry_urls.extend(entry_urls_from_snapshot(seed_snapshot))

    category_queue: list[tuple[str, str]] = []
    product_queue: list[tuple[str, str]] = []
    seen_queue: set[str] = set()
    for url in entry_urls:
        if not url or not url.startswith("http"):
            continue
        normalized = canonical_url(url)
        if normalized in seen_queue or not same_host(normalized, host) or ignored_url(normalized):
            continue
        target_queue = product_queue if product_like_url(normalized) else category_queue
        target_queue.append((normalized, normalized))
        seen_queue.add(normalized)

    visited: set[str] = set()
    category_pages_seen = 0
    records: list[ProductRecord] = []
    notes = [AUTOS_ONLY_NOTE, "Wix category pages are used only as entry points; product detail pages are preferred for real matching support."]

    while category_queue and category_pages_seen < MAX_CATEGORY_PAGES:
        url, source_page_url = category_queue.pop(0)
        if url in visited or ignored_url(url):
            continue
        visited.add(url)
        category_pages_seen += 1
        try:
            final_url, raw, headers = fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Fetch warning for {url}: {exc}")
            continue
        html = decode_html(raw, headers)
        for link in extract_links(html, final_url):
            if link in visited or link in seen_queue:
                continue
            if not same_host(link, host) or ignored_url(link):
                continue
            if product_like_url(link):
                product_queue.append((link, final_url))
                seen_queue.add(link)
            elif category_like_url(link):
                category_queue.append((link, final_url))
                seen_queue.add(link)

    while product_queue and len(records) < MAX_PRODUCTS:
        url, source_page_url = product_queue.pop(0)
        if url in visited or ignored_url(url):
            continue
        visited.add(url)
        try:
            final_url, raw, headers = fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Fetch warning for {url}: {exc}")
            continue
        html = decode_html(raw, headers)
        if not product_like_url(final_url):
            continue
        records.extend(parse_product_page(final_url, html, source_page_url))

    return dedupe_records(records, EXCLUDE_KEYWORDS), list(dict.fromkeys(notes + [MANUAL_NOTE]))


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes = crawl_provider(metadata, seed_snapshot)
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
