#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

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
    slug_to_words,
    provider_paths,
    same_host,
    url_matches_any,
    write_snapshot_bundle,
)

CONFIG = {
    "provider_id": "autorecambiosltda",
    "display_name": "Autorecambios LTDA",
    "max_pages": 1000,
    "max_products": 5000,
    "crawl_category_surfaces": False,
    "category_only_mode": False,
    "prefer_vehicle_match": True,
    "collect_pdf_links": False,
    "image_catalog_only": False,
    "static_entry_urls": (),
    "allow_category_records": False,
    "extra_product_patterns": ("/producto/",),
    "extra_category_patterns": (),
    "disallowed_url_patterns": (),
}
EXCLUDE_KEYWORDS = ("motoc", "bus", "buses", "tracto", "npr", "agricola", "industrial")
VEHICLE_TOKENS = ("chevrolet", "mazda", "renault", "kia", "hyundai", "nissan", "toyota", "ford", "volkswagen")
HEADED_ENV = "AUTORECAMBIOSLTDA_HEADED"
PERSISTENT_ENV = "AUTORECAMBIOSLTDA_PERSISTENT_CONTEXT"
USER_DATA_DIR_ENV = "AUTORECAMBIOSLTDA_USER_DATA_DIR"
WAIT_FOR_HUMAN_ENV = "AUTORECAMBIOSLTDA_WAIT_FOR_HUMAN"
HUMAN_WAIT_TIMEOUT_SECONDS_ENV = "AUTORECAMBIOSLTDA_HUMAN_WAIT_TIMEOUT_SECONDS"
CONSERVATIVE_MODE_ENV = "AUTORECAMBIOSLTDA_CONSERVATIVE_MODE"
DETAIL_WORKERS = 2
BROWSER_SCROLL_PASSES = 12
PROGRESS_STATE_PATH = REPO_ROOT / "local" / "autorecambiosltda_progress.json"
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT_LANGUAGE = "es-CO,es;q=0.9,en;q=0.8"
BLOCKED_TITLE_PATTERNS = (
    "one moment, please",
    "espere mientras se verifica su solicitud",
    "verifica su solicitud",
    "please wait while your request is being verified",
)
BLOCKED_BODY_PATTERNS = (
    "sorry, you have been blocked",
    "you have been blocked",
    "verify you are human",
    "checking your browser before accessing",
    "unusual traffic",
    "cloudflare",
    "attention required",
    "access denied",
)
PRODUCT_LINK_SELECTORS = (
    'a[href*="/producto/"]',
    'a[href*="/product/"]',
)
PAGINATION_LINK_SELECTORS = (
    '.dipl_woo_products_pagination_wrapper a',
    'nav a[href*="/page/"]',
    'nav a.page-numbers',
    '.pagination a[href*="/page/"]',
    '.pagination a.page-numbers',
    'a.page-numbers',
)
PAGINATION_NEXT_SELECTORS = (
    '.dipl_woo_products_pagination_wrapper a:has-text("Next")',
    '.dipl_woo_products_pagination_wrapper a:has-text("Siguiente")',
    'a.page-link:has-text("Next")',
    'nav a.page-link:has-text("Next")',
    '.pagination a.page-link:has-text("Next")',
    'nav a:has-text("Next")',
    'nav button:has-text("Next")',
    '.pagination a:has-text("Next")',
    '.pagination button:has-text("Next")',
    'a:has-text("Next")',
    'button:has-text("Next")',
    'a.page-link:has-text("Siguiente")',
    'nav a.page-link:has-text("Siguiente")',
    '.pagination a.page-link:has-text("Siguiente")',
    'nav a:has-text("Siguiente")',
    'nav button:has-text("Siguiente")',
    '.pagination a:has-text("Siguiente")',
    '.pagination button:has-text("Siguiente")',
    'a:has-text("Siguiente")',
    'button:has-text("Siguiente")',
)
VISIBLE_PRODUCT_LINK_SELECTORS = (
    '.dipl_woo_products_isotope_item a[href*="/producto/"]:visible',
    '.dipl_single_woo_product a[href*="/producto/"]:visible',
    'a[href*="/producto/"]:visible',
    'a[href*="/product/"]:visible',
)
EXPECTED_LISTING_PAGE_COUNT = 24
EXPECTED_PRODUCT_COUNT = 231
LAST_RUN_EVIDENCE: dict[str, object] = {}

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
CRAWL_CATEGORY_SURFACES = CONFIG["crawl_category_surfaces"]


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


def looks_like_blocked_title(value: str | None) -> bool:
    text = (value or "").strip().lower()
    return bool(text) and any(pattern in text for pattern in BLOCKED_TITLE_PATTERNS)


def title_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").split("/")[-1]
    title = slug_to_words(slug)
    return title or url


def normalize_product_records(records: list[ProductRecord], fallback_title: str | None, final_url: str) -> list[ProductRecord]:
    if not records:
        return records
    fallback = fallback_title or title_from_url(final_url)
    normalized: list[ProductRecord] = []
    for record in records:
        title = record.title or record.product_name
        if looks_like_blocked_title(title) or not title:
            title = fallback
        if looks_like_blocked_title(record.product_name) or not record.product_name:
            record.product_name = title
        if looks_like_blocked_title(record.title) or not record.title:
            record.title = title
        if record.searchable_tokens:
            blocked_tokens = {"one", "moment", "please", "captcha", "verify", "verification"}
            if blocked_tokens.intersection({token.lower() for token in record.searchable_tokens}):
                record.searchable_tokens = [token for token in record.searchable_tokens if token.lower() not in blocked_tokens]
                if title and title != fallback:
                    record.searchable_tokens.extend([token for token in fallback.lower().split() if token not in record.searchable_tokens])
        normalized.append(record)
    return normalized


def product_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    return default_product_like_url(url) or url_matches_any(url, EXTRA_PRODUCT_PATTERNS)


def category_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    return default_category_like_url(url) or url_matches_any(url, EXTRA_CATEGORY_PATTERNS)


def listing_surface_seed_url(url: str) -> bool:
    """
    Browser discovery should start from listing/category surfaces only.

    Product URLs can still be parsed later during the detail stage, but they
    should not enter the listing queue because they pollute pagination discovery
    and can stop us before we traverse every page on the catalog surface.
    """

    if ignored_url(url):
        return False
    return category_like_url(url)


def provider_host_matches(url: str, host: str) -> bool:
    candidate = urlparse(url).netloc.lower()
    host = host.lower().strip()
    bare_host = host.removeprefix("www.")
    return candidate == host or candidate == bare_host or candidate == f"www.{bare_host}"


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def bool_metadata(metadata: dict[str, object], key: str, default: bool = False) -> bool:
    value = metadata.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def is_blocked_page(page) -> bool:
    title = ""
    try:
        title = (page.title() or "").lower()
    except Exception:
        pass
    if title and any(pattern in title for pattern in BLOCKED_TITLE_PATTERNS):
        return True
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        pass
    return any(pattern in body_text for pattern in BLOCKED_BODY_PATTERNS)


def human_delay_ms(base_ms: int, jitter_ms: int = 0) -> int:
    conservative = bool_env(CONSERVATIVE_MODE_ENV, True)
    base_ms = max(0, int(base_ms))
    jitter_ms = max(0, int(jitter_ms))
    if conservative:
        base_ms = int(base_ms * 1.35)
        jitter_ms = max(jitter_ms, max(200, base_ms // 5))
    if jitter_ms:
        return base_ms + random.randint(0, jitter_ms)
    return base_ms


def pause_page(page, base_ms: int, jitter_ms: int = 0) -> None:
    try:
        page.wait_for_timeout(human_delay_ms(base_ms, jitter_ms))
    except Exception:
        pass


def int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def wait_for_human_verification(page, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=2000).lower()
        except Exception:
            pass
        if "verifica su solicitud" not in body_text and "captcha" not in body_text and "no soy un robot" not in body_text:
            return True
        log_progress("autorecambiosltda_waiting_human", page_url=page.url, remaining_seconds=max(0, int(deadline - time.monotonic())))
        try:
            page.wait_for_timeout(1000)
        except Exception:
            pass
    return False




def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/autorecambiosltda_catalog_extractor.py`."
        ) from exc
    return sync_playwright


def detect_browser_executable() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip()
    if configured:
        return configured

    cache_root = Path.home() / ".cache" / "ms-playwright"
    for pattern in (
        "chromium-*/chrome-linux64/chrome",
        "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    ):
        for candidate in sorted(cache_root.glob(pattern), reverse=True):
            if candidate.is_file():
                return str(candidate)

    for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge"):
        resolved = shutil.which(candidate)
        if resolved:
            if resolved.startswith("/snap/"):
                continue
            return resolved
    return None


def log_progress(event: str, **payload: object) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)

def persist_progress_state(**payload: object) -> None:
    try:
        PROGRESS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass


def close_popups(page) -> None:
    selectors = (
        '#cmplz-cookiebanner-1-optin',
        '#cmplz-manage-consent',
        '.cmplz-close',
        '.popup .close',
        '.modal .close',
        'button[aria-label="Close"]',
        'button[aria-label="Cerrar"]',
        'button:has-text("Aceptar")',
        'button:has-text("Entendido")',
        'button:has-text("Cerrar")',
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                try:
                    locator.click(timeout=2000)
                except Exception:
                    page.evaluate(
                        """
                        (sel) => {
                          const node = document.querySelector(sel);
                          if (node) node.click();
                        }
                        """,
                        selector,
                    )
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def collect_anchor_data(page, selector: str, host: str) -> list[dict[str, str]]:
    try:
        data = page.locator(selector).evaluate_all(
            """
            els => els.map((el) => ({
              href: el.href || el.getAttribute('href') || '',
              text: (el.innerText || el.textContent || '').trim(),
            })).filter((item) => item.href)
            """
        )
    except Exception:
        data = []
    if selector == "a[href]":
        log_progress(
            "autorecambiosltda_anchor_raw",
            page_url=page.url,
            count=len(data),
            sample=[item.get("href", "") for item in data[:10]],
        )
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        href = item.get("href") or ""
        text = item.get("text") or ""
        try:
            normalized = canonical_url(href)
        except Exception:
            normalized = canonical_url(urljoin(page.url, href))
        if normalized in seen or not provider_host_matches(normalized, host) or ignored_url(normalized):
            continue
        if product_like_url(normalized) or category_like_url(normalized):
            results.append({"url": normalized, "text": text})
            seen.add(normalized)
    return results


def collect_product_anchor_data(page, host: str, visible_only: bool = False) -> list[dict[str, str]]:
    selectors = VISIBLE_PRODUCT_LINK_SELECTORS if visible_only else PRODUCT_LINK_SELECTORS
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for selector in selectors:
        for item in collect_anchor_data(page, selector, host):
            url = item["url"]
            if url in seen or not product_like_url(url):
                continue
            results.append(item)
            seen.add(url)
    return results


def browser_discover_listing_pages(page, host: str) -> list[str]:
    pages: list[str] = []
    seen: set[str] = set()
    for item in collect_anchor_data(page, "a[href]", host):
        url = item["url"]
        if "/page/" in url and url not in seen:
            pages.append(url)
            seen.add(url)
    for selector in PAGINATION_LINK_SELECTORS:
        for item in collect_anchor_data(page, selector, host):
            url = item["url"]
            if "/page/" in url and url not in seen:
                pages.append(url)
                seen.add(url)
    return pages


def browser_discover_pagination_numbers(page) -> list[str]:
    selectors = (
        ".dipl_woo_products_pagination_wrapper li",
        ".dipl_woo_products_pagination_wrapper a",
        "nav .page-item",
        ".pagination li",
        ".pagination a",
        "a.page-numbers",
    )
    numbers: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            texts = page.locator(selector).evaluate_all(
                """
                els => els
                  .map((el) => (el.innerText || el.textContent || '').trim())
                  .filter(Boolean)
                """
            )
        except Exception:
            continue
        for text in texts:
            match = re.search(r"\d+", text or "")
            if not match:
                continue
            value = match.group(0)
            if value not in seen:
                numbers.append(value)
                seen.add(value)
    return numbers


def browser_active_page_number(page) -> str:
    selectors = (
        ".dipl_woo_products_pagination_wrapper li.active",
        "nav .page-item.active",
        ".pagination .active",
        "li.active",
        "a.page-link.active",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                text = locator.first.inner_text(timeout=1000).strip()
            except Exception:
                text = (locator.first.text_content() or "").strip()
            if text:
                match = re.search(r"\d+", text)
                return match.group(0) if match else text
        except Exception:
            continue
    return ""


def browser_collect_current_listing_state(page, host: str, url: str) -> dict[str, object]:
    current_map: dict[str, str] = {}
    visible_items = collect_product_anchor_data(page, host, visible_only=True)
    for item in visible_items:
        item_url = item["url"]
        fallback_title = item["text"].strip()
        if not fallback_title:
            slug = Path(urlparse(item_url).path).name.replace("-", " ").strip()
            fallback_title = slug or item_url
        current_map.setdefault(item_url, fallback_title)

    if not current_map:
        for item in collect_anchor_data(page, "a[href]", host):
            item_url = item["url"]
            if not product_like_url(item_url):
                continue
            fallback_title = item["text"].strip()
            if not fallback_title:
                slug = Path(urlparse(item_url).path).name.replace("-", " ").strip()
                fallback_title = slug or item_url
            current_map.setdefault(item_url, fallback_title)

    current_categories: list[str] = []
    seen_categories: set[str] = set()
    normalized_current = canonical_url(url)
    for item in collect_anchor_data(page, "a[href]", host):
        item_url = item["url"]
        if category_like_url(item_url) and item_url != normalized_current and item_url not in seen_categories:
            current_categories.append(item_url)
            seen_categories.add(item_url)

    current_pages = browser_discover_listing_pages(page, host)
    pagination_numbers = browser_discover_pagination_numbers(page)
    active_page = browser_active_page_number(page)
    ordered_product_urls = list(current_map.keys())
    signature = "|".join(ordered_product_urls)
    return {
        "product_map": current_map,
        "listing_pages": current_pages,
        "category_urls": current_categories,
        "product_urls": ordered_product_urls,
        "pagination_numbers": pagination_numbers,
        "active_page": active_page,
        "signature": signature,
    }


def wait_for_listing_grid_change(page, host: str, url: str, previous_signature: str, previous_active: str) -> dict[str, object] | None:
    deadline = time.monotonic() + 35
    candidate_state: dict[str, object] | None = None
    stable_reads = 0
    while time.monotonic() < deadline:
        try:
            pause_page(page, 900, 300)
        except Exception:
            pass
        close_popups(page)
        if bool_env(WAIT_FOR_HUMAN_ENV, False):
            wait_for_human_verification(page, int_env(HUMAN_WAIT_TIMEOUT_SECONDS_ENV, 900))
        if is_blocked_page(page):
            return None
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            try:
                page.mouse.wheel(0, 1800)
            except Exception:
                pass
        state = browser_collect_current_listing_state(page, host, url)
        current_signature = str(state.get("signature") or "")
        current_active = str(state.get("active_page") or "")
        product_urls = state.get("product_urls") or []
        if not product_urls:
            continue
        if current_signature and current_signature != previous_signature:
            if candidate_state and candidate_state.get("signature") == current_signature:
                stable_reads += 1
            else:
                candidate_state = state
                stable_reads = 0
            if stable_reads >= 1:
                return state
        elif previous_active and current_active and current_active != previous_active:
            candidate_state = state
    return candidate_state if candidate_state and candidate_state.get("signature") != previous_signature else None


def browser_click_next_page(page) -> bool:
    def click_locator(locator) -> bool:
        if locator.count() == 0:
            return False
        target = locator.first
        try:
            target.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            if not target.is_visible(timeout=1000):
                return False
        except Exception:
            pass
        try:
            before_url = page.url
            before_active = browser_active_page_number(page)
            target.click(timeout=5000)
            try:
                pause_page(page, 1800, 600)
            except Exception:
                pass
            after_active = browser_active_page_number(page)
            log_progress("autorecambiosltda_pagination_click", selector=getattr(locator, "selector", ""), before_url=before_url, after_url=page.url, before_active=before_active, after_active=after_active)
            return True
        except Exception:
            return False

    try:
        active_text = ""
        for selector in ('.dipl_woo_products_pagination_wrapper li.active', 'nav .page-item.active', '.pagination .active', 'li.active', 'a.page-link.active'):
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                active_text = locator.first.inner_text(timeout=1000).strip()
            except Exception:
                try:
                    active_text = (locator.first.text_content() or "").strip()
                except Exception:
                    active_text = ""
            if active_text:
                break
        match = re.search(r'\d+', active_text)
        if match:
            next_number = str(int(match.group(0)) + 1)
            numeric_selectors = (
                f'.dipl_woo_products_pagination_wrapper li a:has-text("{next_number}")',
                f'nav .page-item a:has-text("{next_number}")',
                f'nav a.page-link:has-text("{next_number}")',
                f'nav a:has-text("{next_number}")',
                f'.pagination .page-item a:has-text("{next_number}")',
                f'.pagination a.page-link:has-text("{next_number}")',
                f'.pagination a:has-text("{next_number}")',
            )
            for selector in numeric_selectors:
                if click_locator(page.locator(selector)):
                    return True
    except Exception:
        pass
    for selector in PAGINATION_NEXT_SELECTORS:
        try:
            if click_locator(page.locator(selector)):
                return True
        except Exception:
            continue
    return False
def browser_collect_listing_surface(page, host: str, url: str) -> tuple[dict[str, str], list[str], list[str]]:
    best_product_map: dict[str, str] = {}
    best_listing_pages: list[str] = []
    best_category_urls: list[str] = []
    page_evidence: list[dict[str, object]] = []
    page_title = ""
    try:
        page_title = page.title()
    except Exception:
        pass

    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    close_popups(page)
    if bool_env(WAIT_FOR_HUMAN_ENV, False):
        wait_for_human_verification(page, int_env(HUMAN_WAIT_TIMEOUT_SECONDS_ENV, 900))
    if is_blocked_page(page):
        log_progress("autorecambiosltda_blocked_listing", page_url=url, title=page_title)
        return best_product_map, best_listing_pages, best_category_urls
    try:
        page_title = page.title()
    except Exception:
        pass

    stable_passes = 0
    current_state = browser_collect_current_listing_state(page, host, url)
    for scroll_pass in range(BROWSER_SCROLL_PASSES):
        current_state = browser_collect_current_listing_state(page, host, url)
        current_map = current_state["product_map"]
        current_pages = current_state["listing_pages"]
        current_categories = current_state["category_urls"]
        before_count = len(best_product_map)
        best_product_map.update(current_map)
        after_count = len(best_product_map)
        if after_count > before_count:
            stable_passes = 0
        else:
            stable_passes += 1
            if current_pages and not best_listing_pages:
                best_listing_pages = current_pages
            for category_url in current_categories:
                if category_url not in best_category_urls:
                    best_category_urls.append(category_url)
        log_progress(
            "autorecambiosltda_listing_surface_debug",
            page_url=url,
            pass_index=scroll_pass + 1,
            discovered_products=len(current_map),
            discovered_categories=len(current_categories),
            best_products=len(best_product_map),
            discovered_pages=len(current_pages),
            best_pages=len(best_listing_pages),
            sample=list(current_map.items())[:5],
            category_sample=current_categories[:5],
        )
        if best_product_map and stable_passes >= 2:
            break
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            try:
                page.mouse.wheel(0, 2400)
            except Exception:
                pass
        try:
            pause_page(page, 1800, 700)
        except Exception:
            pass
        close_popups(page)
        if bool_env(WAIT_FOR_HUMAN_ENV, False):
            wait_for_human_verification(page, int_env(HUMAN_WAIT_TIMEOUT_SECONDS_ENV, 900))

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        try:
            page.mouse.wheel(0, 2400)
        except Exception:
            pass
    try:
        page.wait_for_timeout(1400)
    except Exception:
        pass

    pagination_stable = 0
    pagination_failures = 0
    current_state = browser_collect_current_listing_state(page, host, url)
    current_map = current_state["product_map"]
    current_pages = current_state["listing_pages"]
    current_categories = current_state["category_urls"]
    if current_pages:
        for discovered in current_pages:
            if discovered not in best_listing_pages:
                best_listing_pages.append(discovered)
    for category_url in current_categories:
        if category_url not in best_category_urls:
            best_category_urls.append(category_url)
    current_page_label = str(current_state.get("active_page") or "1")
    page_evidence.append(
        {
            "page_number": current_page_label,
            "product_count": len(current_map),
            "product_urls": list(current_map.keys()),
            "sample_titles": list(current_map.values())[:5],
            "pagination_numbers": current_state.get("pagination_numbers", []),
        }
    )

    for pagination_step in range(MAX_PAGES):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            try:
                page.mouse.wheel(0, 2400)
            except Exception:
                pass
        try:
            pause_page(page, 1200, 400)
        except Exception:
            pass
        previous_signature = str(current_state.get("signature") or "")
        before_active = str(current_state.get("active_page") or browser_active_page_number(page) or "")
        if not browser_click_next_page(page):
            break
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            try:
                pause_page(page, 1800, 600)
            except Exception:
                pass
        next_state = wait_for_listing_grid_change(page, host, url, previous_signature, before_active)
        if next_state is None:
            pagination_failures += 1
            log_progress(
                "autorecambiosltda_listing_page_retry",
                page_url=url,
                pagination_step=pagination_step + 1,
                active_page=before_active,
                retry_failures=pagination_failures,
            )
            if pagination_failures >= 10:
                break
            continue
        pagination_failures = 0
        current_state = next_state
        current_map = current_state["product_map"]
        current_pages = current_state["listing_pages"]
        current_categories = current_state["category_urls"]
        before_count = len(best_product_map)
        best_product_map.update(current_map)
        after_count = len(best_product_map)
        if after_count > before_count:
            pagination_stable = 0
        else:
            pagination_stable += 1
        if current_pages:
            for discovered in current_pages:
                if discovered not in best_listing_pages:
                    best_listing_pages.append(discovered)
        for category_url in current_categories:
            if category_url not in best_category_urls:
                best_category_urls.append(category_url)
        current_page_label = str(current_state.get("active_page") or "")
        page_evidence.append(
            {
                "page_number": current_page_label or str(pagination_step + 2),
                "product_count": len(current_map),
                "product_urls": list(current_map.keys()),
                "sample_titles": list(current_map.values())[:5],
                "pagination_numbers": current_state.get("pagination_numbers", []),
            }
        )

        log_progress(
            "autorecambiosltda_listing_pagination_debug",
            page_url=url,
            pagination_step=pagination_step + 1,
            discovered_products=len(current_map),
            discovered_categories=len(current_categories),
            best_products=len(best_product_map),
            discovered_pages=len(current_pages),
            stable_passes=pagination_stable,
            sample=list(current_map.items())[:5],
            category_sample=current_categories[:5],
        )
        persist_progress_state(
            stage="listing_surface",
            page_url=url,
            current_page=current_page_label or browser_active_page_number(page),
            page_index=pagination_step + 1,
            current_page_products=len(current_map),
            unique_products=len(best_product_map),
            listing_pages_seen=best_listing_pages,
            category_urls=best_category_urls,
            page_evidence=page_evidence,
            sample_urls=list(best_product_map.keys())[:20],
        )
        if pagination_stable >= 5:
            break

    global LAST_RUN_EVIDENCE
    LAST_RUN_EVIDENCE = {
        "listing_url": url,
        "page_evidence": page_evidence,
        "unique_listing_products": len(best_product_map),
        "listing_pages_seen": best_listing_pages,
        "category_urls": best_category_urls,
    }
    return best_product_map, best_listing_pages, best_category_urls


def browser_fetch_wrapper_props(page) -> dict[str, str]:
    try:
        raw = page.locator(".dipl_woo_products_pagination_wrapper").evaluate(
            """el => Object.fromEntries(Array.from(el.attributes).filter((attr) => attr.name.startsWith('data-')).map((attr) => [attr.name.slice(5), attr.value]))"""
        )
    except Exception:
        return {}
    result: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            result[str(key)] = "" if value is None else str(value)
    return result


def browser_fetch_query_vars(page_url: str) -> dict[str, str]:
    parsed = urlparse(page_url)
    result: dict[str, str] = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        result[key] = value
    return result


def browser_fetch_listing_page_items(page, page_url: str, wrapper_props: dict[str, str], page_number: int) -> list[dict[str, str]]:
    ajax_url = None
    ajax_nonce = None
    try:
        window_data = page.evaluate("""() => window.DiviPlusWooProductsData || {}""")
        if isinstance(window_data, dict):
            ajax_url = window_data.get("ajaxurl")
            ajax_nonce = window_data.get("ajaxnonce")
    except Exception:
        pass
    ajax_url = str(ajax_url or "https://autorecambiosltda.com/wp-admin/admin-ajax.php")
    ajax_nonce = str(ajax_nonce or "")
    query_vars = browser_fetch_query_vars(page_url)
    try:
        payload = page.evaluate(
            """async ({ajaxUrl, ajaxNonce, wrapperProps, pageNumber, queryVars}) => {
                const fd = new FormData();
                fd.append('action', 'dipl_get_woo_products');
                fd.append('dipl_get_woo_products_nonce', ajaxNonce);
                for (const [key, value] of Object.entries(wrapperProps || {})) {
                    if (key === 'page') continue;
                    fd.append(`props[${key}]`, value == null ? '' : String(value));
                }
                fd.set('props[page]', String(pageNumber));
                for (const [key, value] of Object.entries(queryVars || {})) {
                    fd.append(`query_vars[${key}]`, value == null ? '' : String(value));
                }
                const response = await fetch(ajaxUrl, {
                    method: 'POST',
                    body: fd,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    credentials: 'same-origin',
                });
                const text = await response.text();
                let data = null;
                try {
                    data = JSON.parse(text);
                } catch (error) {
                    data = { success: false, raw: text };
                }
                return { status: response.status, data };
            }""",
            {"ajaxUrl": ajax_url, "ajaxNonce": ajax_nonce, "wrapperProps": wrapper_props, "pageNumber": page_number, "queryVars": query_vars},
        )
    except Exception as exc:
        raise RuntimeError(f"AJAX fetch failed for page {page_number}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected AJAX payload for page {page_number}: {type(payload).__name__}")
    status = int(payload.get("status") or 0)
    data = payload.get("data") or {}
    if status != 200 or not isinstance(data, dict) or not data.get("success"):
        raise RuntimeError(f"AJAX response not successful for page {page_number}: status={status}")
    items_html = str(data.get("items") or "")
    if not items_html.strip():
        return []
    try:
        entries = page.evaluate(
            """html => {
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const selectors = [
                    '.dipl_single_woo_product_title a[href]',
                    '.dipl_single_woo_product_thumbnail a[href]',
                    'a[href*="/producto/"]',
                ];
                const seen = new Set();
                const results = [];
                for (const selector of selectors) {
                    for (const anchor of doc.querySelectorAll(selector)) {
                        const href = anchor.href || anchor.getAttribute('href') || '';
                        if (!href || seen.has(href)) continue;
                        const text = (anchor.textContent || anchor.getAttribute('title') || '').trim();
                        results.push({ url: href, text });
                        seen.add(href);
                    }
                }
                return results;
            }""",
            items_html,
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to parse AJAX items for page {page_number}: {exc}") from exc
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            text = str(item.get("text") or "").strip()
            if not url or url in seen or not provider_host_matches(url, urlparse(page_url).netloc):
                continue
            if not text:
                slug = Path(urlparse(url).path).name.replace("-", " ").strip()
                text = slug or url
            result.append({"url": canonical_url(url), "text": text})
            seen.add(url)
    return result


def browser_collect_listing_surface_via_ajax(page, host: str, url: str) -> tuple[dict[str, str], list[str], list[str]]:
    page_title = ""
    try:
        page_title = page.title()
    except Exception:
        pass
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    close_popups(page)
    if bool_env(WAIT_FOR_HUMAN_ENV, False):
        wait_for_human_verification(page, int_env(HUMAN_WAIT_TIMEOUT_SECONDS_ENV, 900))
    if is_blocked_page(page):
        log_progress("autorecambiosltda_blocked_listing", page_url=url, title=page_title)
        return {}, [], []
    wrapper_props = browser_fetch_wrapper_props(page)
    if not wrapper_props:
        raise RuntimeError("Missing wrapper props for pagination AJAX")
    wrapper_props["hide_out_of_stock"] = "off"
    total_pages = int(wrapper_props.get("total_pages") or 1)
    if total_pages < 1:
        total_pages = 1
    best_product_map: dict[str, str] = {}
    best_category_urls: list[str] = []
    page_evidence: list[dict[str, object]] = []
    current_categories: list[str] = []
    seen_categories: set[str] = set()
    normalized_current = canonical_url(url)
    for item in collect_anchor_data(page, "a[href]", host):
        item_url = item["url"]
        if category_like_url(item_url) and item_url != normalized_current and item_url not in seen_categories:
            current_categories.append(item_url)
            seen_categories.add(item_url)
    best_category_urls.extend(current_categories)
    for page_number in range(1, total_pages + 1):
        entries = browser_fetch_listing_page_items(page, url, wrapper_props, page_number)
        current_map: dict[str, str] = {}
        for item in entries:
            item_url = item["url"]
            title = item["text"].strip()
            if not title:
                title = title_from_url(item_url)
            current_map.setdefault(item_url, title)
        if not current_map:
            raise RuntimeError(f"AJAX page {page_number} returned no product links")
        before_count = len(best_product_map)
        best_product_map.update(current_map)
        after_count = len(best_product_map)
        page_evidence.append({
            "page_number": str(page_number),
            "product_count": len(current_map),
            "product_urls": list(current_map.keys()),
            "sample_titles": list(current_map.values())[:5],
            "pagination_numbers": [str(n) for n in range(1, total_pages + 1)],
        })
        log_progress(
            "autorecambiosltda_listing_ajax_page_debug",
            page_url=url,
            page_number=page_number,
            discovered_products=len(current_map),
            unique_products=len(best_product_map),
            sample=list(current_map.items())[:5],
        )
        persist_progress_state(
            stage="listing_surface_ajax",
            page_url=url,
            current_page=str(page_number),
            page_index=page_number,
            current_page_products=len(current_map),
            unique_products=len(best_product_map),
            listing_pages_seen=[],
            category_urls=best_category_urls,
            page_evidence=page_evidence,
            sample_urls=list(best_product_map.keys())[:20],
        )
        if page_number == total_pages and after_count <= before_count:
            break
    global LAST_RUN_EVIDENCE
    LAST_RUN_EVIDENCE = {
        "listing_url": url,
        "page_evidence": page_evidence,
        "unique_listing_products": len(best_product_map),
        "listing_pages_seen": [],
        "category_urls": best_category_urls,
    }
    return best_product_map, [], best_category_urls


def collect_records_for_product_url(url: str, source_page_url: str, infer_match_type_fn, fallback_title: str | None = None) -> tuple[list[ProductRecord], str | None]:
    try:
        final_url, raw, headers = fetch_url(url)
        html = decode_html(raw, headers)
    except Exception as exc:  # noqa: BLE001
        if fallback_title:
            record = ProductRecord(
                item_type="product",
                provider_type="product_catalog_partial",
                product_name=fallback_title,
                product_url=url,
                detail_url=url,
                source_page_url=source_page_url,
                page_number=1,
                match_type="manual_confirmation_required",
                match_confidence="low",
                requires_manual_confirmation=True,
                searchable_tokens=[fallback_title.lower(), "autorecambios", "catalogo"],
            )
            return [record], f"Fetch warning for {url}: {exc}"
        return [], f"Fetch warning for {url}: {exc}"

    if ignored_url(final_url):
        return [], None

    content_type = headers.get("content-type", "").lower()
    if "pdf" in content_type or final_url.lower().endswith(".pdf"):
        return [], None

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
        infer_match_type=infer_match_type_fn,
    )
    product_records = normalize_product_records(product_records, fallback_title, final_url)
    if not product_records:
        fallback = parse_product_fallback(
            url=final_url,
            html=html,
            source_page_url=source_page_url,
            category_only_mode=CATEGORY_ONLY_MODE,
            infer_match_type=infer_match_type_fn,
        )
        if fallback:
            fallback = normalize_product_records([fallback], fallback_title, final_url)[0]
            product_records = [fallback]
        elif fallback_title:
            product_records = [
                ProductRecord(
                    item_type="product",
                    provider_type="product_catalog_partial",
                    title=fallback_title,
                    product_name=fallback_title,
                    product_url=final_url,
                    detail_url=final_url,
                    description=meta_description,
                    source_page_url=source_page_url,
                    page_number=1,
                    match_type="manual_confirmation_required",
                    match_confidence="low",
                    requires_manual_confirmation=True,
                    searchable_tokens=[token for token in fallback_title.lower().split() if token] + ["autorecambios", "catalogo"],
                )
            ]
    return product_records, None


def crawl_static_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    entry_urls = [str(metadata.get("catalog_root_url") or metadata.get("website") or "")]
    entry_urls.extend(STATIC_ENTRY_URLS)
    metadata_static_urls = metadata.get("static_entry_urls") or []
    if isinstance(metadata_static_urls, list):
        entry_urls.extend(str(url) for url in metadata_static_urls if str(url).strip())
    if seed_snapshot:
        seed_urls = [url for url in entry_urls_from_snapshot(seed_snapshot) if category_like_url(url) or product_like_url(url)]
        entry_urls.extend(seed_urls)

    queue: list[tuple[str, str]] = []
    seen_queue: set[str] = set()
    seed_urls: set[str] = set()
    for url in entry_urls:
        if not url or not url.startswith("http"):
            continue
        normalized = canonical_url(url)
        if normalized not in seen_queue and provider_host_matches(normalized, host):
            queue.append((normalized, normalized))
            seen_queue.add(normalized)
            seed_urls.add(normalized)

    visited: set[str] = set()
    records: list[ProductRecord] = []
    notes = [AUTOS_ONLY_NOTE]

    while queue and len(visited) < MAX_PAGES and len(records) < MAX_PRODUCTS:
        url, source_page_url = queue.pop(0)
        if url in visited or (url not in seed_urls and ignored_url(url)):
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
            if not provider_host_matches(link, host) or ignored_url(link):
                continue
            if COLLECT_PDF_LINKS and link.lower().endswith(".pdf"):
                queue.append((link, final_url))
                seen_queue.add(link)
                continue
            if product_like_url(link) or (bool_metadata(metadata, "crawl_category_surfaces", CRAWL_CATEGORY_SURFACES) and category_like_url(link)):
                queue.append((link, final_url))
                seen_queue.add(link)

    return dedupe_records(records, EXCLUDE_KEYWORDS), list(dict.fromkeys(notes + [MANUAL_NOTE]))


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    entry_urls = [str(metadata.get("catalog_root_url") or metadata.get("website") or "")]
    entry_urls.extend(STATIC_ENTRY_URLS)
    metadata_static_urls = metadata.get("static_entry_urls") or []
    if isinstance(metadata_static_urls, list):
        entry_urls.extend(str(url) for url in metadata_static_urls if str(url).strip())
    if seed_snapshot:
        seed_urls = [url for url in entry_urls_from_snapshot(seed_snapshot) if category_like_url(url) or product_like_url(url)]
        entry_urls.extend(seed_urls)

    notes = [AUTOS_ONLY_NOTE]
    records: list[ProductRecord] = []
    product_map: dict[str, str] = {}
    listing_pages_seen: set[str] = set()

    browser_available = True
    browser_error = ""
    try:
        sync_playwright = get_playwright()
    except SystemExit as exc:
        browser_available = False
        browser_error = str(exc)

    if browser_available:
        with sync_playwright() as playwright:
            launch_kwargs: dict[str, object] = {"headless": not bool_env(HEADED_ENV, False), "args": ["--disable-blink-features=AutomationControlled"]}
            if bool_env(HEADED_ENV, False) or bool_env(CONSERVATIVE_MODE_ENV, True):
                launch_kwargs["slow_mo"] = 120
            browser_path = detect_browser_executable()
            if browser_path:
                launch_kwargs["executable_path"] = browser_path
            browser = None
            if bool_env(PERSISTENT_ENV, False):
                user_data_dir = os.environ.get(USER_DATA_DIR_ENV, "").strip()
                if not user_data_dir:
                    raise SystemExit(f"{USER_DATA_DIR_ENV} must be set when {PERSISTENT_ENV} is enabled.")
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    viewport={"width": 1440, "height": 960},
                    locale="es-CO",
                    user_agent=DEFAULT_BROWSER_USER_AGENT,
                    extra_http_headers={"Accept-Language": DEFAULT_ACCEPT_LANGUAGE},
                    **launch_kwargs,
                )
                page = context.pages[0] if context.pages else context.new_page()
            else:
                browser = playwright.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 960},
                    locale="es-CO",
                    user_agent=DEFAULT_BROWSER_USER_AGENT,
                    extra_http_headers={"Accept-Language": DEFAULT_ACCEPT_LANGUAGE},
                )
                page = context.new_page()
            queue: list[str] = []
            seen_queue: set[str] = set()
            seed_urls: set[str] = set()
            for url in entry_urls:
                if not url or not url.startswith("http"):
                    continue
                normalized = canonical_url(url)
                if normalized not in seen_queue and provider_host_matches(normalized, host) and listing_surface_seed_url(normalized):
                    queue.append(normalized)
                    seen_queue.add(normalized)
                    seed_urls.add(normalized)
            while queue and len(listing_pages_seen) < MAX_PAGES:
                current_url = queue.pop(0)
                if current_url in listing_pages_seen or (current_url not in seed_urls and ignored_url(current_url)):
                    continue
                listing_pages_seen.add(current_url)
                try:
                    page_product_map, discovered_pages, discovered_categories = browser_collect_listing_surface_via_ajax(page, host, current_url)
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"Browser listing warning for {current_url}: {exc}")
                    continue
                log_progress(
                    "autorecambiosltda_listing_page_debug",
                    page_url=current_url,
                    page_products=len(page_product_map),
                    page_pages=len(discovered_pages),
                    page_categories=len(discovered_categories),
                    sample=list(page_product_map.items())[:5],
                    category_sample=discovered_categories[:5],
                )
                for product_url, title in page_product_map.items():
                    product_map.setdefault(product_url, title)
                for next_url in discovered_pages:
                    if next_url not in seen_queue and next_url not in listing_pages_seen:
                        queue.append(next_url)
                        seen_queue.add(next_url)
                if bool_metadata(metadata, "crawl_category_surfaces", CRAWL_CATEGORY_SURFACES):
                    for category_url in discovered_categories:
                        if category_url not in seen_queue and category_url not in listing_pages_seen:
                            queue.append(category_url)
                            seen_queue.add(category_url)
                log_progress(
                    "autorecambiosltda_listing_page",
                    page_url=current_url,
                    discovered_products=len(product_map),
                    discovered_pages=len(listing_pages_seen),
                    queued_pages=len(queue),
                )
                persist_progress_state(
                    stage="browser_listing_page",
                    page_url=current_url,
                    discovered_products=len(product_map),
                    discovered_pages=len(listing_pages_seen),
                    queued_pages=len(queue),
                    listing_pages_seen=sorted(listing_pages_seen),
                    product_urls_sample=list(product_map.keys())[:20],
                )
                if len(product_map) >= MAX_PRODUCTS:
                    break
            context.close()
            if browser is not None:
                browser.close()

    debug_path = REPO_ROOT / "local" / "autorecambiosltda_browser_debug.json"
    try:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(
            json.dumps(
                {
                    "entry_urls": entry_urls,
                    "listing_pages_seen": sorted(listing_pages_seen),
                    "product_map_count": len(product_map),
                    "product_map_sample": list(product_map.items())[:20],
                    "browser_available": browser_available,
                    "browser_error": browser_error,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    if product_map:
        listing_records: list[ProductRecord] = []
        log_progress(
            "autorecambiosltda_detail_seed",
            discovered_products=len(product_map),
            sample=list(product_map.items())[:5],
        )
        for product_url, title in product_map.items():
            tokens = [token for token in re.split(r"\W+", title.lower()) if token]
            listing_records.append(
                ProductRecord(
                    item_type="product",
                    provider_type="product_catalog_partial",
                    title=title,
                    product_name=title,
                    product_url=product_url,
                    detail_url=product_url,
                    description=title,
                    source_page_url=entry_urls[0],
                    page_number=1,
                    match_type="manual_confirmation_required",
                    match_confidence="low",
                    requires_manual_confirmation=True,
                    searchable_tokens=tokens + ["autorecambios", "catalogo"],
                )
            )
        records.extend(listing_records)
        notes.append("Catalogo extraido desde la grilla AJAX completa con hide_out_of_stock=off; detalles omitidos para evitar timeouts en paginas de producto.")
        if records:
            deduped_records = dedupe_records(records, EXCLUDE_KEYWORDS)
            evidence_pages = LAST_RUN_EVIDENCE.get("page_evidence", []) if isinstance(LAST_RUN_EVIDENCE, dict) else []
            visible_listing_urls = list(
                dict.fromkeys(
                    url
                    for page_info in evidence_pages
                    for url in page_info.get("product_urls", [])
                )
            )
            final_record_urls = {
                record.detail_url or record.product_url
                for record in deduped_records
            }
            missing_visible_urls = [url for url in visible_listing_urls if url and url not in final_record_urls]
            if missing_visible_urls:
                notes.append(
                    "Productos visibles en la grilla pero ausentes del snapshot final: "
                    f"{len(missing_visible_urls)}. Ejemplos: {', '.join(missing_visible_urls[:5])}. "
                    "Causa probable: descarte por normalizacion o filtro residual."
                )
            observed_page_numbers = [
                int(str(page_info.get("page_number") or "0"))
                for page_info in evidence_pages
                if str(page_info.get("page_number") or "").isdigit()
            ]
            max_observed_page = max(observed_page_numbers, default=0)
            if len(visible_listing_urls) < EXPECTED_PRODUCT_COUNT or max_observed_page < EXPECTED_LISTING_PAGE_COUNT:
                raise RuntimeError(
                    "Extraccion incompleta de la grilla principal de Autorecambios LTDA: "
                    f"{len(visible_listing_urls)} productos unicos visibles, "
                    f"paginas observadas hasta {max_observed_page or 'sin detectar'}, "
                    f"esperado aproximado {EXPECTED_PRODUCT_COUNT} productos en {EXPECTED_LISTING_PAGE_COUNT} paginas."
                )
            return deduped_records, list(dict.fromkeys(notes + [MANUAL_NOTE]))

    static_records, static_notes = crawl_static_provider(metadata, seed_snapshot)
    return static_records, list(dict.fromkeys(notes + static_notes))


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
    extracted_path = write_snapshot_bundle(output_root=output_root, snapshot_date=snapshot_day, payload=payload, products=products)
    evidence = LAST_RUN_EVIDENCE if isinstance(LAST_RUN_EVIDENCE, dict) else {}
    if evidence:
        evidence_path = extracted_path.parent / "pagination_evidence.json"
        evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
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












































