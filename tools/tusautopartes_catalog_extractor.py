#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
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
    dedupe_records,
    decode_html,
    fetch_url,
    latest_snapshot_json,
    load_json,
    normalize_text,
    provider_paths,
    same_host,
    slug_to_words,
    write_snapshot_bundle,
)

PROVIDER_ID = "tusautopartes"
DISPLAY_NAME = "Tus Autopartes"
ROOT_URL = "https://tusautopartes.com.co/"
ROOT_HOST = urlparse(ROOT_URL).netloc.lower()
MENU_IDS = (
    "HeaderMenu-MenuList-2",
    "HeaderMenu-MenuList-3",
    "HeaderMenu-MenuList-4",
    "HeaderMenu-MenuList-5",
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
EXCLUDE_KEYWORDS: tuple[str, ...] = ()
MAX_COLLECTION_PAGES = 12

MENU_BLOCK_RE = re.compile(r'<ul[^>]*id="([^"]+)"[^>]*>(.*?)</ul>', re.IGNORECASE | re.DOTALL)
MENU_LINK_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
CARD_BLOCK_RE = re.compile(
    r'<div class="card-wrapper product-card-wrapper underline-links-hover">(.*?)</li>',
    re.IGNORECASE | re.DOTALL,
)
CARD_LINK_RE = re.compile(
    r'<a[^>]*href="(/products/[^"]+)"[^>]*id="CardLink-[^"]+"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
CARD_IMAGE_RE = re.compile(r'<img[^>]*(?:src|data-src)="([^"]+)"[^>]*alt="([^"]*)"', re.IGNORECASE | re.DOTALL)
NEXT_PAGE_RE = re.compile(
    r'<a[^>]*rel="next"[^>]*href="([^"]+)"|<a[^>]*class="[^"]*pagination__item--next[^"]*"[^>]*href="([^"]+)"|<a[^>]*aria-label="Next"[^>]*href="([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("/feed/", ".rss", ".xml"))


def infer_match_type(title: str | None, collection_name: str | None) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, collection_name])).lower()
    if any(token in allowed_text for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", False
    return "category_only", "medium", True


def discover_collections(home_html: str) -> list[dict[str, str]]:
    collections: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for menu_id in MENU_IDS:
        exact_match = re.search(
            rf'<ul[^>]*id="{re.escape(menu_id)}"[^>]*>(.*?)</ul>',
            home_html,
            re.IGNORECASE | re.DOTALL,
        )
        if not exact_match:
            continue
        block = exact_match.group(1)
        for href, text in MENU_LINK_RE.findall(block):
            absolute = canonical_url(urljoin(ROOT_URL, href))
            if ignored_url(absolute) or not absolute.startswith(ROOT_URL):
                continue
            if "/collections/" not in absolute:
                continue
            name = normalize_text(re.sub(r'<[^>]+>', ' ', text))
            if not name or absolute in seen_urls:
                continue
            collections.append({"collection_name": name, "collection_url": absolute, "menu_id": menu_id})
            seen_urls.add(absolute)
    return collections


def next_collection_page_url(html: str, current_url: str) -> str | None:
    match = NEXT_PAGE_RE.search(html)
    if not match:
        return None
    href = next(group for group in match.groups() if group)
    resolved = canonical_url(urljoin(current_url, href))
    if resolved == canonical_url(current_url):
        return None
    return resolved


def extract_collection_products(html: str, page_url: str, collection_name: str) -> list[ProductRecord]:
    page_number = 1
    records: list[ProductRecord] = []
    blocks = CARD_BLOCK_RE.findall(html)
    if not blocks:
        blocks = [html]
    for block in blocks:
        link_match = CARD_LINK_RE.search(block)
        if not link_match:
            continue
        detail_url = canonical_url(urljoin(page_url, link_match.group(1)))
        if ignored_url(detail_url):
            continue

        title = normalize_text(link_match.group(2))
        if not title:
            title = slug_to_words(detail_url.rstrip("/").rsplit("/", 1)[-1]) or None

        image_match = CARD_IMAGE_RE.search(block)
        image_url = canonical_url(urljoin(page_url, image_match.group(1))) if image_match else None
        image_alt = normalize_text(image_match.group(2)) if image_match else None

        match_type, match_confidence, requires_manual_confirmation = infer_match_type(title, collection_name)
        records.append(
            ProductRecord(
                item_type="product",
                provider_type="product_catalog",
                title=title,
                product_name=title,
                detail_url=detail_url,
                product_url=detail_url,
                category_name=collection_name,
                subcategory_name=None,
                brand=None,
                reference=None,
                sku=None,
                supplier_item_code=None,
                description=None,
                vehicle_scope=None,
                image_url=image_url,
                source_page_url=page_url,
                page_number=page_number,
                match_type=match_type,
                match_confidence=match_confidence,
                requires_manual_confirmation=requires_manual_confirmation,
                searchable_tokens=build_searchable_tokens(title, collection_name, image_alt),
            )
        )
    return records


def crawl_collection(collection_name: str, collection_url: str) -> tuple[list[ProductRecord], list[str], int]:
    notes: list[str] = []
    records: list[ProductRecord] = []
    page_count = 0
    current_url = canonical_url(collection_url)
    visited_pages: set[str] = set()

    while current_url and current_url not in visited_pages and page_count < MAX_COLLECTION_PAGES:
        visited_pages.add(current_url)
        page_count += 1
        try:
            final_url, raw, headers = fetch_url(current_url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Fetch warning for {current_url}: {exc}")
            break

        if ignored_url(final_url):
            break

        html = decode_html(raw, headers)
        if not html.strip():
            notes.append(f"Empty response for {final_url}")
            break

        page_records = extract_collection_products(html, final_url, collection_name)
        records.extend(page_records)

        next_url = next_collection_page_url(html, final_url)
        if next_url and next_url not in visited_pages and same_host(next_url, ROOT_HOST):
            current_url = next_url
            continue
        break

    if not records:
        notes.append(f"Collection {collection_name} returned no visible products.")
    else:
        notes.append(f"Collection {collection_name}: extracted {len(records)} visible product(s) across {page_count} page(s).")
    return records, notes, page_count


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str], list[dict[str, object]], dict[str, list[str]]]:
    home_url = canonical_url(str(metadata.get("website") or ROOT_URL))
    try:
        final_home_url, raw_home, home_headers = fetch_url(home_url)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Failed to fetch home page {home_url}: {exc}") from exc

    home_html = raw_home.decode(home_headers.get("charset", "utf-8") if home_headers.get("charset") else "utf-8", errors="replace")
    collections = discover_collections(home_html)
    if not collections:
        raise SystemExit("No header collections discovered for Tus Autopartes.")

    notes = [AUTOS_ONLY_NOTE, f"Discovered {len(collections)} collections from the Shopify header menu at {final_home_url}."]
    if seed_snapshot:
        notes.append("Seed snapshot was available, but the crawl now treats the live Shopify collections as the source of truth.")

    product_map: dict[str, ProductRecord] = {}
    product_collections: dict[str, list[str]] = defaultdict(list)
    collection_summaries: list[dict[str, object]] = []
    total_visible = 0
    total_pages = 0

    for collection in collections:
        collection_name = collection["collection_name"]
        collection_url = collection["collection_url"]
        page_records, page_notes, page_count = crawl_collection(collection_name, collection_url)
        notes.extend(page_notes)
        total_pages += page_count
        total_visible += len(page_records)
        collection_product_urls: list[str] = []

        for record in page_records:
            key = record.detail_url or record.product_url or ""
            if not key:
                continue
            collection_product_urls.append(key)
            if key not in product_map:
                product_map[key] = record
            if collection_name not in product_collections[key]:
                product_collections[key].append(collection_name)

        collection_summaries.append(
            {
                "collection_name": collection_name,
                "collection_url": collection_url,
                "menu_id": collection["menu_id"],
                "page_count": page_count,
                "product_count": len(collection_product_urls),
                "unique_product_count": len(dict.fromkeys(collection_product_urls)),
                "product_urls": list(dict.fromkeys(collection_product_urls)),
            }
        )

    unique_products = list(product_map.values())
    duplicate_count = sum(1 for names in product_collections.values() if len(names) > 1)
    notes.append(f"Crawl reached {len(collections)} collections and {total_pages} page fetch(es) across the header menu.")
    notes.append(f"Extracted {len(unique_products)} unique product(s) from {total_visible} visible card(s).")
    notes.append(f"Found {duplicate_count} duplicated product URL(s) shared across multiple collections.")
    return dedupe_records(unique_products, EXCLUDE_KEYWORDS), list(dict.fromkeys(notes + [MANUAL_NOTE])), collection_summaries, product_collections


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes, collection_summaries, product_collections = crawl_provider(metadata, seed_snapshot)
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=products,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    payload["collections"] = collection_summaries
    payload["product_collections"] = product_collections
    payload["collection_count"] = len(collection_summaries)
    payload["unique_product_count"] = len(products)
    payload["duplicate_product_count"] = sum(1 for names in product_collections.values() if len(names) > 1)
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
