#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

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
    url_matches_any,
    write_snapshot_bundle,
)

CONFIG = {'provider_id': 'ppaautomotriz', 'display_name': 'PPA Automotriz', 'max_pages': 320, 'max_products': 500, 'category_only_mode': False, 'prefer_vehicle_match': True, 'collect_pdf_links': False, 'image_catalog_only': False, 'static_entry_urls': (), 'allow_category_records': False, 'extra_product_patterns': ('/producto/',), 'extra_category_patterns': (), 'disallowed_url_patterns': ()}
EXCLUDE_KEYWORDS = ('moto', 'motoc', 'camiones', 'bus', 'buses', 'tracto', 'npr', 'diesel', 'agricola', 'industrial')
VEHICLE_TOKENS = ('chevrolet', 'mazda', 'renault', 'kia', 'hyundai', 'nissan', 'toyota', 'ford', 'volkswagen')

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


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    entry_urls = [str(metadata.get("catalog_root_url") or metadata.get("website") or "" )]
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
    records: list[ProductRecord] = []
    notes = [AUTOS_ONLY_NOTE]

    while queue and len(visited) < MAX_PAGES and len(records) < MAX_PRODUCTS:
        url, source_page_url = queue.pop(0)
        if url in visited or ignored_url(url):
            continue
        visited.add(url)
        try:
            final_url, raw, headers = fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Fetch warning for {url}: {exc}")
            continue

        if ignored_url(final_url):
            continue

        content_type = headers.get("content-type", "").lower()
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            if COLLECT_PDF_LINKS:
                records.extend(parse_pdf_records(f'<a href="{final_url}">{DISPLAY_NAME}</a>', final_url, source_page_url))
            continue

        html = decode_html(raw, headers)
        if COLLECT_PDF_LINKS:
            records.extend(parse_pdf_records(html, final_url, source_page_url))

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

        is_product_page = bool(product_records) or product_like_url(final_url)
        if is_product_page and not product_records:
            fallback = parse_product_fallback(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                category_only_mode=CATEGORY_ONLY_MODE,
                infer_match_type=infer_match_type,
            )
            if fallback:
                product_records = [fallback]

        if product_records:
            records.extend(product_records)
        elif ALLOW_CATEGORY_RECORDS and (category_like_url(final_url) or final_url in entry_urls):
            category_record = parse_category_record(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                exclude_keywords=EXCLUDE_KEYWORDS,
                match_type="category_only" if CATEGORY_ONLY_MODE else "manual_confirmation_required",
            )
            if category_record:
                records.append(category_record)

        for link in extract_links(html, final_url):
            if link in visited or link in seen_queue:
                continue
            if not same_host(link, host) or ignored_url(link):
                continue
            if COLLECT_PDF_LINKS and link.lower().endswith(".pdf"):
                queue.append((link, final_url))
                seen_queue.add(link)
                continue
            if product_like_url(link) or category_like_url(link):
                queue.append((link, final_url))
                seen_queue.add(link)

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

    return dedupe_records(records, EXCLUDE_KEYWORDS), list(dict.fromkeys(notes + [MANUAL_NOTE]))


BROWSER_SCROLL_PASSES = int(os.environ.get("PPAAUTOMOTRIZ_SCROLL_PASSES", "12"))
BROWSER_SCROLL_PAUSE_MS = int(os.environ.get("PPAAUTOMOTRIZ_SCROLL_PAUSE_MS", "900"))
BROWSER_MAX_LISTINGS = int(os.environ.get("PPAAUTOMOTRIZ_BROWSER_MAX_LISTINGS", "40"))
BROWSER_HEADLESS = os.environ.get("PPAAUTOMOTRIZ_HEADED", "").strip().lower() not in {"1", "true", "yes", "on"}
BROWSER_PERSISTENT_CONTEXT = os.environ.get("PPAAUTOMOTRIZ_PERSISTENT_CONTEXT", "1").strip().lower() in {"1", "true", "yes", "on"}
BROWSER_USER_DATA_DIR = Path(os.environ.get("PPAAUTOMOTRIZ_USER_DATA_DIR", REPO_ROOT / "local" / "browser_profiles" / "ppaautomotriz"))




def debug_enabled() -> bool:
    return os.environ.get("PPAAUTOMOTRIZ_DEBUG", "").strip().lower() in {"1", "true", "yes", "on", "debug"}



def debug_log(message: str) -> None:
    if debug_enabled():
        print(f"[ppaautomotriz] {message}", flush=True)

def detect_browser_executable() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip()
    if configured:
        return configured
    for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None



def browser_launch_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {"headless": BROWSER_HEADLESS}
    executable = detect_browser_executable()
    if executable:
        kwargs["executable_path"] = executable
    return kwargs



def clear_browser_overlays(page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    selectors = [
        "#appView .powrModal",
        "#appView .popupApp",
        "#appView .powrModal.popupApp",
        "#appView .popupPowrMarkContainer",
        "#cmplz-cookiebanner-container",
        "#cmplz-cookiebanner-1-optin",
        "#onetrust-banner-sdk",
        "[id*='cookie']",
        "[class*='cookie']",
        "[class*='popup']",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                try:
                    locator.first.click(timeout=1500)
                except Exception:
                    page.evaluate(
                        """
                        (sel) => {
                          const node = document.querySelector(sel);
                          if (node) {
                            try { node.click(); } catch (err) {}
                          }
                        }
                        """,
                        selector,
                    )
        except Exception:
            pass
    try:
        page.evaluate(
            """
            (selectors) => {
              for (const selector of selectors) {
                for (const node of document.querySelectorAll(selector)) {
                  try {
                    node.style.display = 'none';
                    node.style.visibility = 'hidden';
                    node.style.pointerEvents = 'none';
                  } catch (err) {}
                }
              }
            }
            """,
            selectors,
        )
    except Exception:
        pass



def collect_links_from_page(page, host: str) -> set[str]:
    try:
        hrefs = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href]'))
              .map((node) => node.href || node.getAttribute('href') || '')
              .filter(Boolean)
            """
        )
    except Exception:
        hrefs = []
    links: set[str] = set()
    for href in hrefs:
        normalized = canonical_url(str(href))
        if not normalized or not normalized.startswith('http'):
            continue
        if same_host(normalized, host) and not ignored_url(normalized):
            links.add(normalized)
    return links



def scroll_page_until_stable(page, host: str) -> set[str]:
    seen: set[str] = set()
    stable_rounds = 0
    previous_total = 0
    for _ in range(max(BROWSER_SCROLL_PASSES, 1) * 4):
        clear_browser_overlays(page)
        seen.update(collect_links_from_page(page, host))
        current_total = len(seen)
        if current_total == previous_total:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_total = current_total
        if stable_rounds >= 3:
            break
        try:
            page.mouse.wheel(0, 2600)
        except Exception:
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight || document.documentElement.scrollHeight || 0)")
            except Exception:
                pass
        page.wait_for_timeout(BROWSER_SCROLL_PAUSE_MS)
    return seen



def discover_catalog_sources_browser(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[dict[str, str], list[str]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    entry_url = canonical_url(str(metadata.get("catalog_root_url") or metadata.get("website") or ""))
    discovered_sources: dict[str, str] = {}
    notes: list[str] = []
    if not entry_url or not same_host(entry_url, host):
        return discovered_sources, ["Browser discovery could not resolve a valid entry URL."]
    with sync_playwright() as playwright:
        browser = None
        context = None
        try:
            if BROWSER_PERSISTENT_CONTEXT:
                BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_USER_DATA_DIR),
                    viewport={"width": 1440, "height": 1800},
                    locale="es-CO",
                    **browser_launch_kwargs(),
                )
                page = context.pages[0] if context.pages else context.new_page()
            else:
                browser = playwright.chromium.launch(**browser_launch_kwargs())
                context = browser.new_context(viewport={"width": 1440, "height": 1800}, locale="es-CO")
                page = context.new_page()
            page.set_default_timeout(15000)
            page.set_default_navigation_timeout(60000)
            try:
                debug_log(f"Visiting listing page: {entry_url}")
                page.goto(entry_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001
                return discovered_sources, [f"Browser listing fetch warning for {entry_url}: {exc}"]
            clear_browser_overlays(page)
            page_links = scroll_page_until_stable(page, host)
            if not page_links:
                notes.append(f"No links discovered while browsing {entry_url}")
            for link in page_links:
                if product_like_url(link):
                    discovered_sources.setdefault(link, entry_url)
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
    notes.append(f"Browser discovery found {len(discovered_sources)} product URLs from the root listing page.")
    debug_log(f"Browser discovery found {len(discovered_sources)} product URLs from the root listing page.")
    return discovered_sources, notes

def fetch_product_record(url: str, source_page_url: str) -> tuple[list[ProductRecord], list[str]]:
    try:
        final_url, raw, headers = fetch_url(url)
    except Exception as exc:  # noqa: BLE001
        return [], [f"Fetch warning for {url}: {exc}"]
    if ignored_url(final_url):
        return [], []
    content_type = headers.get("content-type", "").lower()
    if "pdf" in content_type or final_url.lower().endswith(".pdf"):
        return [], []
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
    is_product_page = bool(product_records) or product_like_url(final_url)
    if is_product_page and not product_records:
        fallback = parse_product_fallback(
            url=final_url,
            html=html,
            source_page_url=source_page_url,
            category_only_mode=CATEGORY_ONLY_MODE,
            infer_match_type=infer_match_type,
        )
        if fallback:
            product_records = [fallback]
    if product_records:
        return product_records, []
    return [], []



def fetch_product_records_parallel(product_sources: dict[str, str]) -> tuple[list[ProductRecord], list[str]]:
    records: list[ProductRecord] = []
    notes: list[str] = []
    if not product_sources:
        return records, notes
    max_workers = min(12, max(1, len(product_sources)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_product_record, url, source_page_url): url
            for url, source_page_url in product_sources.items()
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                product_records, product_notes = future.result()
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Product fetch warning for {url}: {exc}")
                continue
            records.extend(product_records)
            notes.extend(product_notes)
    return dedupe_records(records, EXCLUDE_KEYWORDS), list(dict.fromkeys(notes))



def crawl_provider_browser(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    notes = [AUTOS_ONLY_NOTE]
    browser_product_sources: dict[str, str] = {}
    browser_notes: list[str] = []
    try:
        browser_product_sources, browser_notes = discover_catalog_sources_browser(metadata, seed_snapshot)
        notes.extend(browser_notes)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Browser discovery failed: {exc}")
    browser_records: list[ProductRecord] = []
    if browser_product_sources:
        browser_records, fetch_notes = fetch_product_records_parallel(browser_product_sources)
        notes.extend(fetch_notes)
    else:
        notes.append("Browser discovery did not surface product URLs; using the legacy HTML crawler as fallback.")
    if browser_product_sources and len(browser_product_sources) >= 20:
        legacy_records, legacy_notes = [], []
        notes.append(f"Browser discovery found enough product URLs to skip the legacy fallback ({len(browser_product_sources)} URLs).")
    else:
        legacy_records, legacy_notes = crawl_provider(metadata, seed_snapshot)
    notes.extend(legacy_notes)
    notes.append(MANUAL_NOTE)
    combined = dedupe_records(browser_records + legacy_records, EXCLUDE_KEYWORDS)
    return combined, list(dict.fromkeys(notes))
def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes = crawl_provider_browser(metadata, seed_snapshot)
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












