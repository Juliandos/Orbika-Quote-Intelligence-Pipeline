#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
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
    dedupe_records,
    fetch_url,
    guess_page_number,
    latest_snapshot_json,
    load_json,
    normalize_text,
    provider_paths,
    slug_to_words,
    url_matches_any,
    write_snapshot_bundle,
)

PROVIDER_ID = "totus"
DISPLAY_NAME = "Totus"
ROOT_URL = "https://www.totus.com.co/tienda/"
MAX_PAGE_GUARD = 400
VEHICLE_TOKENS = ("chevrolet", "mazda", "renault", "kia", "hyundai", "nissan", "toyota", "ford", "volkswagen")
EXCLUDE_KEYWORDS: tuple[str, ...] = ()

PAGE_NUMBER_RE = re.compile(r"/tienda/page/(\d+)/", re.IGNORECASE)
PRODUCT_BLOCK_RE = re.compile(
    r'<li\b[^>]*class="[^"]*\bproduct\b[^"]*\btype-product\b[^"]*"[^>]*>(.*?)</li>',
    re.IGNORECASE | re.DOTALL,
)
DETAIL_LINK_RE = re.compile(r'href="([^"]*?/productos/[^"]*?)"', re.IGNORECASE)
TITLE_RE = re.compile(
    r'<h3\b[^>]*class="[^"]*woocommerce-loop-product__title[^"]*"[^>]*>(.*?)</h3>',
    re.IGNORECASE | re.DOTALL,
)
IMAGE_RE = re.compile(r'<img\b[^>]*(?:data-src|src)="([^"]+)"', re.IGNORECASE)
TAG_RE = re.compile(r'<a\b[^>]*rel="tag"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("/feed/", ".rss", ".xml"))


def infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, category_name, description, reference])).lower()
    if any(token in allowed_text for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", False
    if title or category_name:
        return "category_only", "medium", True
    return "manual_confirmation_required", "low", True


def discover_max_page(html: str) -> int:
    page_numbers = [int(match) for match in PAGE_NUMBER_RE.findall(html)]
    return max(page_numbers) if page_numbers else 1


def page_url_for(root_url: str, page_number: int) -> str:
    root = root_url if root_url.endswith("/") else f"{root_url}/"
    if page_number <= 1:
        return canonical_url(root)
    return canonical_url(urljoin(root, f"page/{page_number}/"))


def extract_listing_records(html: str, page_url: str) -> list[ProductRecord]:
    records: list[ProductRecord] = []
    page_number = guess_page_number(page_url)
    for block in PRODUCT_BLOCK_RE.findall(html):
        link_match = DETAIL_LINK_RE.search(block)
        if not link_match:
            continue
        detail_url = canonical_url(urljoin(page_url, normalize_text(link_match.group(1))))
        if ignored_url(detail_url):
            continue

        title_match = TITLE_RE.search(block)
        title = normalize_text(title_match.group(1)) if title_match else None
        if not title:
            title = slug_to_words(urlparse(detail_url).path.rstrip("/").rsplit("/", 1)[-1]) or None

        tags = [normalize_text(tag) for tag in TAG_RE.findall(block)]
        tags = [tag for tag in tags if tag]
        category_name = tags[0] if tags else None
        subcategory_name = tags[1] if len(tags) > 1 else None
        brand = tags[-1] if len(tags) > 2 else None
        vehicle_scope = " | ".join(tags[1:]) if len(tags) > 1 else None

        image_match = IMAGE_RE.search(block)
        image_url = canonical_url(urljoin(page_url, image_match.group(1))) if image_match else None

        match_type, match_confidence, requires_manual_confirmation = infer_match_type(
            title=title,
            category_name=category_name,
            description=vehicle_scope,
            reference=None,
        )

        records.append(
            ProductRecord(
                item_type="product",
                provider_type="product_catalog",
                title=title,
                product_name=title,
                detail_url=detail_url,
                product_url=detail_url,
                category_name=category_name,
                subcategory_name=subcategory_name,
                brand=brand,
                description=None,
                vehicle_scope=vehicle_scope,
                image_url=image_url,
                source_page_url=page_url,
                page_number=page_number,
                match_type=match_type,
                match_confidence=match_confidence,
                requires_manual_confirmation=requires_manual_confirmation,
                searchable_tokens=build_searchable_tokens(title, category_name, subcategory_name, brand, vehicle_scope),
            )
        )
    return records


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    root_url = canonical_url(str(metadata.get("catalog_root_url") or ROOT_URL))
    notes = [AUTOS_ONLY_NOTE]
    if seed_snapshot:
        notes.append("Seed snapshot was available, but the crawl now treats the live /tienda/ surface as the source of truth.")

    discovered_pages = 1
    records: list[ProductRecord] = []
    seen_products: set[str] = set()
    visited_pages: set[str] = set()

    for page_number in range(1, MAX_PAGE_GUARD + 1):
        page_url = page_url_for(root_url, page_number)
        if page_url in visited_pages:
            break
        visited_pages.add(page_url)

        try:
            final_url, raw, headers = fetch_url(page_url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Fetch warning for {page_url}: {exc}")
            if page_number == 1:
                break
            continue

        if ignored_url(final_url):
            continue

        html = decode_html(raw, headers)
        if page_number == 1:
            discovered_pages = max(discovered_pages, discover_max_page(html))
            notes.append(f"Discovered live pagination up to page {discovered_pages} from {final_url}.")

        page_records = extract_listing_records(html, final_url)
        if not page_records:
            notes.append(f"No product cards found on {final_url}; stopping at page {page_number}.")
            break

        added = 0
        for record in page_records:
            key = record.detail_url or record.product_url or ""
            if not key or key in seen_products:
                continue
            seen_products.add(key)
            records.append(record)
            added += 1

        notes.append(f"Page {page_number}: extracted {added} new product(s) from {final_url}.")
        if page_number >= discovered_pages:
            break

    notes.append(f"Final crawl covered {len(visited_pages)} page(s) and collected {len(records)} unique product(s) before dedupe.")
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
