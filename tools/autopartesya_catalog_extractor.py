#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
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

CONFIG = {
    "provider_id": "autopartesya",
    "display_name": "Autopartesya",
    "listing_root_url": "https://www.autopartesya.co/shop-2/",
    "max_products": 50000,
    "max_listing_pages_guard": 5000,
    "prefer_vehicle_match": True,
}

EXCLUDE_KEYWORDS = (
    "moto",
    "motoc",
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
PRODUCT_LINK_SELECTOR = 'a[href*="/product/"], a[href*="/producto/"]'
PAGINATION_LINK_SELECTOR = 'a[href*="/shop-2/page/"]'
AUTOPARTESYA_LISTING_PAUSE_MS = 700
AUTOPARTESYA_SCROLL_PASSES = 4
AUTOPARTESYA_DETAIL_WORKERS = 12

PROVIDER_ID = CONFIG["provider_id"]
DISPLAY_NAME = CONFIG["display_name"]
LISTING_ROOT_URL = CONFIG["listing_root_url"]
MAX_PRODUCTS = CONFIG["max_products"]
MAX_LISTING_PAGES_GUARD = CONFIG["max_listing_pages_guard"]
PREFER_VEHICLE_MATCH = CONFIG["prefer_vehicle_match"]


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with "
            "`uv run --with playwright python tools/autopartesya_catalog_extractor.py`."
        ) from exc
    return sync_playwright


def detect_browser_executable() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip()
    if configured:
        return configured
    for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def log_progress(event: str, **payload: object) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    return ignored_by_keywords(lowered, EXCLUDE_KEYWORDS)


def is_product_url(url: str) -> bool:
    lowered = url.lower()
    return "/product/" in lowered or "/producto/" in lowered


def guess_page_number_from_url(url: str) -> int:
    match = re.search(r"/page/(\d+)(?:/|$)", url)
    if match:
        return int(match.group(1))
    return 1


def listing_page_url(page_number: int) -> str:
    if page_number <= 1:
        return LISTING_ROOT_URL
    return f"https://www.autopartesya.co/shop-2/page/{page_number}/"

def close_blocking_popups(page) -> None:
    try:
        page.evaluate(
            """
            () => {
              const selectors = [
                '[class*="modal"]',
                '[class*="popup"]',
                '[class*="cookie"]',
                '[id*="modal"]',
                '[id*="popup"]',
                '[id*="cookie"]',
                '.powrModal',
                '.popupApp',
                '#cmplz-cookiebanner-container',
                '#cmplz-cookiebanner-1-optin',
                '.modal',
                '.popup',
              ];
              const containers = [];
              for (const selector of selectors) {
                containers.push(...Array.from(document.querySelectorAll(selector)));
              }
              for (const container of containers) {
                const buttons = Array.from(container.querySelectorAll('button, a, [role="button"]'));
                for (const button of buttons) {
                  const label = (button.innerText || button.textContent || button.getAttribute('aria-label') || '').trim().toLowerCase();
                  if (!label) {
                    continue;
                  }
                  if (label.includes('acept') || label.includes('accept') || label.includes('cerrar') || label.includes('close') || label.includes('entendid') || label === 'Ã—' || label === 'x') {
                    button.click();
                    return true;
                  }
                }
              }
              return false;
            }
            """
        )
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def discover_page_numbers(page) -> set[int]:
    numbers: set[int] = set()
    try:
        hrefs = page.locator(PAGINATION_LINK_SELECTOR).evaluate_all(
            "els => els.map((el) => el.href || el.getAttribute('href') || '').filter(Boolean)"
        )
    except Exception:
        hrefs = []
    for href in hrefs:
        match = re.search(r"/page/(\d+)(?:/|$|\\?)", href)
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def collect_product_links(page, host: str) -> list[str]:
    try:
        hrefs = page.locator(PRODUCT_LINK_SELECTOR).evaluate_all(
            "els => els.map((el) => el.href || el.getAttribute('href') || '').filter(Boolean)"
        )
    except Exception:
        hrefs = []

    seen: set[str] = set()
    urls: list[str] = []
    for href in hrefs:
        try:
            normalized = canonical_url(href)
        except Exception:
            continue
        if not normalized.startswith("http"):
            continue
        if ignored_url(normalized):
            continue
        if not same_host(normalized, host):
            continue
        if not is_product_url(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def settle_listing_page(page, host: str, page_number: int) -> list[str]:
    stable_rounds = 0
    last_count = -1
    collected: list[str] = []
    for _ in range(AUTOPARTESYA_SCROLL_PASSES):
        close_blocking_popups(page)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        page.wait_for_timeout(AUTOPARTESYA_LISTING_PAUSE_MS)
        close_blocking_popups(page)
        collected = collect_product_links(page, host)
        current_count = len(collected)
        if current_count <= last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = current_count
        if stable_rounds >= 2:
            break
    log_progress("autopartesya_listing_settled", page_number=page_number, discovered_links=len(collected))
    return collected

def infer_match_type(
    title: str | None,
    category_name: str | None,
    description: str | None,
    reference: str | None,
) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, category_name, description])).lower()
    if any(token in allowed_text for token in VEHICLE_TOKENS) and PREFER_VEHICLE_MATCH:
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def parse_product_records(product_url: str, source_page_url: str, notes: list[str]) -> list[ProductRecord]:
    try:
        final_url, raw, headers = fetch_url(product_url)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Fetch warning for {product_url}: {exc}")
        return []

    if ignored_url(final_url):
        return []

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
            category_only_mode=False,
            infer_match_type=infer_match_type,
        )
        if fallback:
            product_records = [fallback]

    page_number = guess_page_number_from_url(source_page_url)
    adjusted_records: list[ProductRecord] = []
    for record in product_records:
        try:
            if getattr(record, "page_number", None) != page_number:
                record = replace(record, page_number=page_number)
        except Exception:
            pass
        adjusted_records.append(record)
    return adjusted_records


def parse_product_records_with_notes(product_url: str, source_page_url: str) -> tuple[list[ProductRecord], list[str]]:
    notes: list[str] = []
    records = parse_product_records(product_url, source_page_url, notes)
    return records, notes


def crawl_listing_urls(notes: list[str]) -> dict[str, str]:
    sync_playwright = get_playwright()
    browser_path = detect_browser_executable()
    headed = bool_env("AUTOPARTESYA_HEADED", False)
    slow_mo = int(os.environ.get("AUTOPARTESYA_SLOW_MO", "30") or "30")
    persistent_context = bool_env("AUTOPARTESYA_PERSISTENT_CONTEXT", False)
    user_data_dir = os.environ.get("AUTOPARTESYA_USER_DATA_DIR", "").strip()
    if persistent_context and not user_data_dir:
        persistent_context = False

    product_sources: dict[str, str] = {}
    with sync_playwright() as playwright:
        launch_kwargs = {"headless": not headed, "slow_mo": slow_mo}
        if browser_path:
            launch_kwargs["executable_path"] = browser_path

        browser = None
        context = None
        try:
            if persistent_context:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    viewport={"width": 1440, "height": 960},
                    **launch_kwargs,
                )
            else:
                browser = playwright.chromium.launch(**launch_kwargs)
                context = browser.new_context(viewport={"width": 1440, "height": 960})

            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LISTING_ROOT_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            close_blocking_popups(page)

            max_page = max(discover_page_numbers(page) or {1})
            if max_page <= 1:
                notes.append("La paginaciÃ³n inicial no devolviÃ³ mÃ¡s de una pÃ¡gina; el extractor seguirÃ¡ igual y se apoyarÃ¡ en la navegaciÃ³n del navegador.")
            log_progress("autopartesya_listing_start", discovered_max_page=max_page, listing_root=LISTING_ROOT_URL)

            current_page = 1
            while current_page <= max_page and current_page <= MAX_LISTING_PAGES_GUARD:
                target_url = listing_page_url(current_page)
                if current_page == 1:
                    if canonical_url(page.url) != canonical_url(target_url):
                        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(1200)
                else:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1200)

                close_blocking_popups(page)
                product_links = settle_listing_page(page, urlparse(LISTING_ROOT_URL).netloc.lower(), current_page)
                for product_url in product_links:
                    product_sources.setdefault(product_url, canonical_url(page.url))

                discovered_pages = discover_page_numbers(page)
                if discovered_pages:
                    discovered_max = max(discovered_pages)
                    if discovered_max > max_page:
                        max_page = discovered_max
                        notes.append(f"Se ampliÃ³ la paginaciÃ³n detectada a {max_page} pÃ¡ginas.")

                log_progress(
                    "autopartesya_listing_page",
                    page_number=current_page,
                    discovered_links=len(product_links),
                    unique_products=len(product_sources),
                    max_page=max_page,
                    page_url=canonical_url(page.url),
                )

                if len(product_sources) >= MAX_PRODUCTS:
                    notes.append(f"Se alcanzÃ³ el lÃ­mite de productos configurado ({MAX_PRODUCTS}).")
                    break

                current_page += 1

        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    return product_sources

def load_seed_product_urls(metadata: dict[str, object], seed_snapshot: dict[str, object] | None, product_sources: dict[str, str]) -> int:
    added = 0
    if not seed_snapshot:
        return added
    fallback_source = str(metadata.get("catalog_root_url") or metadata.get("website") or LISTING_ROOT_URL)
    for entry in seed_snapshot.get("products", []):
        if not isinstance(entry, dict):
            continue
        candidate_url = entry.get("product_url") or entry.get("detail_url")
        source_page_url = entry.get("source_page_url") or fallback_source
        if not isinstance(candidate_url, str) or not candidate_url.startswith("http"):
            continue
        if not is_product_url(candidate_url):
            continue
        normalized = canonical_url(candidate_url)
        if normalized not in product_sources:
            product_sources[normalized] = str(source_page_url)
            added += 1
    return added


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    notes = [AUTOS_ONLY_NOTE]
    product_sources = crawl_listing_urls(notes)
    seed_added = load_seed_product_urls(metadata, seed_snapshot, product_sources)
    notes.append(
        f"Se descubrieron {len(product_sources)} URLs de detalle antes del parseo "
        f"({seed_added} agregadas desde snapshot previo)."
    )

    records: list[ProductRecord] = []
    parse_failures: list[dict[str, str]] = []
    parse_attempted = 0
    parse_succeeded = 0
    parse_succeeded_urls = 0

    workers = max(1, int(os.environ.get("AUTOPARTESYA_DETAIL_WORKERS", str(AUTOPARTESYA_DETAIL_WORKERS)) or AUTOPARTESYA_DETAIL_WORKERS))
    source_items = list(product_sources.items())
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(parse_product_records_with_notes, product_url, source_page_url): (product_url, source_page_url)
            for product_url, source_page_url in source_items
        }
        for index, future in enumerate(as_completed(futures), start=1):
            product_url, source_page_url = futures[future]
            parse_attempted += 1
            try:
                parsed_records, product_notes = future.result()
            except Exception as exc:  # noqa: BLE001
                if len(parse_failures) < 100:
                    parse_failures.append({"product_url": product_url, "source_page_url": source_page_url})
                notes.append(f"Detalle fallÃ³ para {product_url}: {exc}")
                continue
            if product_notes:
                notes.extend(product_notes)
            if not parsed_records:
                if len(parse_failures) < 100:
                    parse_failures.append({"product_url": product_url, "source_page_url": source_page_url})
                continue
            records.extend(parsed_records)
            parse_succeeded += len(parsed_records)
            parse_succeeded_urls += 1
            if index == 1 or index % 50 == 0:
                log_progress(
                    "autopartesya_parse_progress",
                    attempted=parse_attempted,
                    parsed=parse_succeeded,
                    parsed_urls=parse_succeeded_urls,
                    failed=max(0, parse_attempted - parse_succeeded_urls),
                    workers=workers,
                )

    deduped = dedupe_records(records, EXCLUDE_KEYWORDS)
    notes.append(
        f"Parseo de detalle: {parse_succeeded}/{parse_attempted} productos convertidos "
        f"y {len(deduped)} despuÃ©s de deduplicaciÃ³n."
    )
    if parse_failures:
        notes.append(f"Fallos de detalle muestreados: {json.dumps(parse_failures[:10], ensure_ascii=False)}")
    return deduped, list(dict.fromkeys(notes + [MANUAL_NOTE]))


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


