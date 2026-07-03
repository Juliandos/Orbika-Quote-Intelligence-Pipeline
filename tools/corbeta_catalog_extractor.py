#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
import sys
from urllib.parse import urljoin, urlparse

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
    url_matches_any,
    write_snapshot_bundle,
)

CONFIG = {
    "provider_id": "corbeta",
    "display_name": "Corbeta",
    "max_listing_pages": 250,
    "max_products": 2000,
    "category_only_mode": False,
    "prefer_vehicle_match": True,
    "collect_pdf_links": False,
    "image_catalog_only": False,
    "static_entry_urls": (),
    "allow_category_records": False,
    "extra_product_patterns": (".html",),
    "extra_category_patterns": (),
    "disallowed_url_patterns": (),
}

START_URL = "https://www.corbeta.com.co/automotriz/llantas.html"
EXCLUDE_KEYWORDS = (
    "moto",
    "motoc",
    "moton",
    "camiones",
    "bus",
    "buses",
    "tracto",
    "npr",
    "diesel",
    "agricola",
    "industrial",
)
VEHICLE_TOKENS = ("chevrolet", "mazda", "renault", "kia", "hyundai", "nissan", "toyota", "ford", "volkswagen")

PROVIDER_ID = CONFIG["provider_id"]
DISPLAY_NAME = CONFIG["display_name"]
MAX_LISTING_PAGES = CONFIG["max_listing_pages"]
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

LISTING_PAGE_RE = re.compile(r"https://www\.corbeta\.com\.co/automotriz/llantas\.html(?:\?p=\d+)?", re.IGNORECASE)
PRODUCT_LINK_RE = re.compile(
    r'<h2 class="product-name">\s*<a href="([^"]+)" title="([^"]+)">',
    re.IGNORECASE | re.DOTALL,
)
NEXT_PAGE_RE = re.compile(
    r'<a[^>]+class="next i-next"[^>]+href="([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
BRAND_FILTER_RE = re.compile(
    r'<a id="marca-(\d+)" href="" class="chweb_layered_attribute\s*"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)


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
    lowered = url.lower()
    return any(token in lowered for token in ("/automotriz/llantas/", ".html")) or url_matches_any(url, EXTRA_PRODUCT_PATTERNS)


def category_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    lowered = url.lower()
    return "llantas.html" in lowered or url_matches_any(url, EXTRA_CATEGORY_PATTERNS)


def _is_autos_tire_title(title: str | None, href: str | None = None, description: str | None = None) -> bool:
    text = " ".join(filter(None, [title, href, description])).lower()
    return bool(text) and not any(keyword in text for keyword in EXCLUDE_KEYWORDS)


def _extract_listing_links(html: str, base_url: str) -> tuple[list[str], str | None]:
    product_urls: list[str] = []
    seen_products: set[str] = set()
    for href, title in PRODUCT_LINK_RE.findall(html):
        absolute = canonical_url(urljoin(base_url, href))
        if not same_host(absolute, urlparse(base_url).netloc.lower()):
            continue
        if not _is_autos_tire_title(title, absolute):
            continue
        if absolute in seen_products:
            continue
        seen_products.add(absolute)
        product_urls.append(absolute)

    next_match = NEXT_PAGE_RE.search(html)
    next_url = canonical_url(urljoin(base_url, next_match.group(1))) if next_match else None
    return product_urls, next_url


def _extract_brand_filters(html: str) -> list[tuple[str, str]]:
    brands: list[tuple[str, str]] = []
    seen: set[str] = set()
    for brand_id, brand_name in BRAND_FILTER_RE.findall(html):
        brand_name = " ".join(brand_name.split())
        if not brand_id or not brand_name or brand_id in seen:
            continue
        seen.add(brand_id)
        brands.append((brand_id, brand_name))
    return brands


def _extract_brand_filters_from_page(page) -> list[tuple[str, str]]:
    try:
        locator = page.locator('#chweb_layered_marca a[id^="marca-"]')
        count = locator.count()
        brands: list[tuple[str, str]] = []
        for index in range(count):
            node = locator.nth(index)
            brand_id = node.get_attribute('id') or ''
            brand_name = ' '.join((node.inner_text() or '').split())
            if not brand_id or not brand_name:
                continue
            brands.append((brand_id.removeprefix('marca-'), brand_name))
        if brands:
            return brands
    except Exception:
        pass
    return []


def _load_listing_pages(start_url: str, host: str) -> tuple[list[str], dict[str, str], list[str]]:
    queue: list[str] = [start_url]
    seen_pages: set[str] = set()
    seen_products: set[str] = set()
    product_sources: dict[str, str] = {}
    product_urls: list[str] = []
    notes: list[str] = []
    page_count = 0

    while queue and page_count < MAX_LISTING_PAGES:
        page_url = canonical_url(queue.pop(0))
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        try:
            final_url, raw, headers = fetch_url(page_url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Corbeta listing fetch warning for {page_url}: {exc}")
            continue

        if not same_host(final_url, host) or ignored_url(final_url):
            continue

        content_type = headers.get("content-type", "").lower()
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            continue

        page_count += 1
        html = decode_html(raw, headers)
        listing_products, next_url = _extract_listing_links(html, final_url)
        for product_url in listing_products:
            if product_url in seen_products:
                continue
            seen_products.add(product_url)
            product_urls.append(product_url)
            product_sources[product_url] = final_url

        if next_url and same_host(next_url, host) and next_url not in seen_pages:
            queue.append(next_url)

        for candidate in re.findall(r'href="([^"]+llantas\.html(?:\?p=\d+)?)"', html, re.IGNORECASE):
            normalized = canonical_url(urljoin(final_url, candidate))
            if same_host(normalized, host) and normalized not in seen_pages and normalized not in queue:
                queue.append(normalized)

    notes.append(f"Corbeta listing pages crawled: {page_count}")
    notes.append(f"Corbeta product links discovered: {len(product_urls)}")
    return product_urls, product_sources, notes


def _browser_collect_brand_urls(start_url: str, host: str) -> tuple[list[str], dict[str, str], list[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return [], {}, [f"Playwright unavailable for Corbeta browser crawl: {exc}"]

    product_urls: list[str] = []
    seen_products: set[str] = set()
    product_sources: dict[str, str] = {}
    notes: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        brands = _extract_brand_filters_from_page(page)
        if not brands:
            brands = _extract_brand_filters(page.content())
        notes.append(f"Corbeta browser brand filters discovered: {len(brands)}")
        if not brands:
            browser.close()
            return [], {}, notes

        for brand_id, brand_name in brands:
            if len(product_urls) >= MAX_PRODUCTS:
                break
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1200)
                brand_locator = page.locator(f"#marca-{brand_id}")
                if brand_locator.count() == 0:
                    continue
                brand_locator.first.click(timeout=5000, force=True)
                page.wait_for_timeout(3000)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Corbeta browser brand warning for {brand_name}: {exc}")
                continue

            seen_page_fingerprints: set[tuple[str, ...]] = set()
            for _ in range(20):
                html = page.content()
                listing_products, _ = _extract_listing_links(html, page.url)
                fingerprint = tuple(listing_products)
                if fingerprint in seen_page_fingerprints:
                    break
                seen_page_fingerprints.add(fingerprint)
                new_in_page = False
                for product_url in listing_products:
                    if product_url in seen_products:
                        continue
                    seen_products.add(product_url)
                    product_urls.append(product_url)
                    product_sources[product_url] = page.url
                    new_in_page = True

                next_locator = page.locator("a.next.i-next:visible")
                if next_locator.count() == 0:
                    break
                try:
                    before_signature = json.dumps(listing_products, ensure_ascii=False)
                    advanced = False
                    for _attempt in range(6):
                        next_locator.last.click(timeout=5000, force=True)
                        page.wait_for_timeout(2200)
                        current_signature = json.dumps(
                            page.locator('h2.product-name a').evaluate_all('(els) => els.map(a => a.href)'),
                            ensure_ascii=False,
                        )
                        if current_signature != before_signature:
                            advanced = True
                            break
                    if not advanced:
                        break
                except Exception:
                    break
                if not new_in_page and tuple(_extract_listing_links(page.content(), page.url)[0]) in seen_page_fingerprints:
                    break

        browser.close()

    notes.append(f"Corbeta browser product links discovered: {len(product_urls)}")
    return product_urls, product_sources, notes


def _parse_product_page(url: str, source_page_url: str, html: str) -> ProductRecord | None:
    page_title = extract_page_title(html)
    meta_description = extract_meta_content(html, "description")
    meta_image = extract_meta_content(html, "og:image")
    json_ld_nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)]

    product_records = product_from_json_ld(
        url=url,
        page_title=page_title,
        description=meta_description,
        image_url=meta_image,
        source_page_url=source_page_url,
        json_ld_nodes=json_ld_nodes,
        infer_match_type=infer_match_type,
    )
    if product_records:
        record = product_records[0]
        if _is_autos_tire_title(record.product_name or record.title, url, record.description):
            return record
        return None

    fallback = parse_product_fallback(
        url=url,
        html=html,
        source_page_url=source_page_url,
        category_only_mode=CATEGORY_ONLY_MODE,
        infer_match_type=infer_match_type,
    )
    if fallback and _is_autos_tire_title(fallback.product_name or fallback.title, url, fallback.description):
        return fallback
    return None


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("website") or START_URL)).netloc.lower()

    entry_urls = [str(metadata.get("catalog_root_url") or START_URL)]
    entry_urls.extend(STATIC_ENTRY_URLS)
    if seed_snapshot:
        entry_urls.extend(entry_urls_from_snapshot(seed_snapshot))

    start_url = next(
        (
            canonical_url(url)
            for url in entry_urls
            if url and url.startswith("http") and same_host(url, host)
        ),
        START_URL,
    )

    notes = [AUTOS_ONLY_NOTE]
    listing_product_urls, product_sources, listing_notes = _load_listing_pages(start_url, host)
    notes.extend(listing_notes)

    browser_urls, browser_sources, browser_notes = _browser_collect_brand_urls(start_url, host)
    notes.extend(browser_notes)
    for url in browser_urls:
        if url not in product_sources:
            product_sources[url] = browser_sources.get(url, start_url)
    for url in browser_urls:
        if url not in listing_product_urls:
            listing_product_urls.append(url)

    records: list[ProductRecord] = []
    seen_product_pages: set[str] = set()
    for product_url in listing_product_urls:
        if len(records) >= MAX_PRODUCTS:
            break
        if product_url in seen_product_pages:
            continue
        seen_product_pages.add(product_url)
        try:
            final_url, raw, headers = fetch_url(product_url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Corbeta product fetch warning for {product_url}: {exc}")
            continue
        if not same_host(final_url, host) or ignored_url(final_url):
            continue
        if "pdf" in headers.get("content-type", "").lower() or final_url.lower().endswith(".pdf"):
            continue
        html = decode_html(raw, headers)
        record = _parse_product_page(final_url, product_sources.get(product_url, start_url), html)
        if record:
            records.append(record)

    if ALLOW_CATEGORY_RECORDS and not records:
        try:
            final_url, raw, _headers = fetch_url(start_url)
            html = decode_html(raw, _headers)
            category_record = parse_product_fallback(
                url=final_url,
                html=html,
                source_page_url=start_url,
                category_only_mode=True,
                infer_match_type=infer_match_type,
            )
            if category_record:
                records.append(category_record)
        except Exception:
            pass

    if IMAGE_CATALOG_ONLY and not records:
        records.append(
            ProductRecord(
                item_type="category",
                provider_type="category_only",
                title=DISPLAY_NAME,
                detail_url=start_url,
                category_name=DISPLAY_NAME,
                description="Catalogo visual publico; la extraccion viva se mantiene como verificacion manual.",
                source_page_url=start_url,
                match_type="manual_confirmation_required",
                match_confidence="low",
                requires_manual_confirmation=True,
                searchable_tokens=[DISPLAY_NAME.lower(), "catalogo", "visual"],
            )
        )

    notes.append(MANUAL_NOTE)
    return dedupe_records(records, EXCLUDE_KEYWORDS), list(dict.fromkeys(notes))


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
