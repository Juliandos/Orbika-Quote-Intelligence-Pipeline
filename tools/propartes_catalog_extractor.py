#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlparse

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
    guess_page_number,
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
    normalize_text,
    url_matches_any,
    write_snapshot_bundle,
)

CONFIG = {
    "provider_id": "propartes",
    "display_name": "Propartes",
    "max_pages": 5000,
    "max_products": 20000,
    "category_only_mode": False,
    "prefer_vehicle_match": True,
    "collect_pdf_links": False,
    "image_catalog_only": False,
    "static_entry_urls": (
        "https://tienda.propartes.com/filtros-automotriz",
        "https://tienda.propartes.com/filtros-de-combustible/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/filtros-de-aire-cabina/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/filtros-de-aire/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/filtros-de-aceite/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/refrigerantes-autos/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/frenos-automotriz",
        "https://tienda.propartes.com/liquido-frenos-386/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/sensor-desgaste/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/pastilla-freno-71/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/disco-freno/products?pageNumber=1&productLowPrice=0&productHighPrice=10000000&sort=1&attributes=%5B%5D",
        "https://tienda.propartes.com/bombillos-y-exploradoras/products",
    ),
    "allow_category_records": False,
    "extra_product_patterns": (
        "/producto/",
        "/product/",
        "/product-page/",
        "/producto-",
    ),
    "extra_category_patterns": (
        "/filtros-automotriz",
        "/filtros-de-combustible/products?pageNumber=",
        "/filtros-de-aire-cabina/products?pageNumber=",
        "/filtros-de-aire/products?pageNumber=",
        "/filtros-de-aceite/products?pageNumber=",
        "/refrigerantes-autos/products?pageNumber=",
        "/frenos-automotriz",
        "/liquido-frenos-386/products?pageNumber=",
        "/sensor-desgaste/products?pageNumber=",
        "/pastilla-freno-71/products?pageNumber=",
        "/disco-freno/products?pageNumber=",
        "/bombillos-y-exploradoras/products",
    ),
    "disallowed_url_patterns": (),
}
EXCLUDE_KEYWORDS = ("moto", "motoc", "camiones", "bus", "buses", "tracto", "npr", "diesel", "agricola", "industrial")
VEHICLE_TOKENS = ("chevrolet", "mazda", "renault", "kia", "hyundai", "nissan", "toyota", "ford", "volkswagen")
PROPARTES_NON_PRODUCT_TAILS = {
    "products",
    "product",
    "producto",
    "catalogo",
    "home",
    "autos",
    "filtros-automotriz",
    "frenos-automotriz",
    "politics",
    "pages",
    "page",
}
PROPARTES_PRODUCT_ROOTS = {
    "filtros-de-combustible",
    "filtros-de-aire-cabina",
    "filtros-de-aire",
    "filtros-de-aceite",
    "refrigerantes-autos",
    "liquido-frenos-386",
    "sensor-desgaste",
    "pastilla-freno-71",
    "disco-freno",
    "bombillos-y-exploradoras",
}
PROPARTES_LISTING_ROOTS = PROPARTES_PRODUCT_ROOTS | {"frenos-automotriz", "filtros-automotriz"}
PROPARTES_MAX_PAGE_NUMBER = 250
PROPARTES_STORE_HOST = "tienda.propartes.com"

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



def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/propartes_catalog_extractor.py`."
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


def is_debug_enabled() -> bool:
    return os.environ.get("PROPARTES_DEBUG", "").strip().lower() in {"1", "true", "yes", "on", "debug"}



def propartes_debug_root() -> Path:
    return REPO_ROOT / "local" / "propartes_debug"



def sanitize_debug_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:80] or "page"



def save_propartes_debug_snapshot(*, page, seed_url: str, final_url: str, stage: str, note: str | None = None) -> None:
    if not is_debug_enabled():
        return
    try:
        root = propartes_debug_root()
        root.mkdir(parents=True, exist_ok=True)
        run_dir = root / date.today().isoformat()
        run_dir.mkdir(parents=True, exist_ok=True)
        slug = sanitize_debug_name(stage)
        html_path = run_dir / f"{slug}.html"
        meta_path = run_dir / f"{slug}.json"
        text_path = run_dir / f"{slug}.txt"
        screenshot_path = run_dir / f"{slug}.png"
        html = page.content()
        visible_text = page.evaluate("document.body ? document.body.innerText : ''") if page else ""
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            screenshot_path = None
        html_path.write_text(html, encoding="utf-8")
        text_path.write_text(visible_text[:20000], encoding="utf-8")
        try:
            pagination_text = page.evaluate("Array.from(document.querySelectorAll('ngb-pagination')).map((node) => node.innerText || '').join('\n---\n')")
        except Exception:
            pagination_text = ""
        try:
            modal_texts = page.evaluate(
                """
                Array.from(document.querySelectorAll('body *'))
                  .filter((node) => {
                    const style = window.getComputedStyle(node);
                    return style && style.position === 'fixed' && parseInt(style.zIndex || '0', 10) >= 1000;
                  })
                  .map((node) => (node.innerText || node.textContent || '').trim())
                  .filter(Boolean)
                  .slice(0, 10)
                """
            )
        except Exception:
            modal_texts = []
        payload = {
            "seed_url": seed_url,
            "final_url": final_url,
            "stage": stage,
            "note": note,
            "title": page.title() if page else None,
            "visible_text_chars": len(visible_text),
            "visible_text_preview": (visible_text[:4000] if visible_text else ""),
            "pagination_text": pagination_text,
            "modal_texts": modal_texts,
            "html_path": str(html_path),
            "text_path": str(text_path),
            "screenshot_path": str(screenshot_path) if screenshot_path else None,
        }
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def clear_propartes_overlays(page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    close_selectors = [
        "#appView .powrModal .closeIcon",
        "#appView .powrModal .powr-popup-close",
        "#appView .powrModal [class*='close']",
        "#appView .powrModal [aria-label='Close']",
        "#appView .powrModal [aria-label='close']",
        "button[aria-label='Close']",
        "button[aria-label='close']",
        "button:has-text('×')",
        "button:has-text('X')",
        "button:has-text('Cerrar')",
        "button:has-text('Entendido')",
        "button:has-text('Estoy de Acuerdo')",
        "button:has-text('Aceptar')",
        "button:has-text('Aceptar todo')",
        ".modal button.close",
        ".modal .close",
        ".popup button.close",
    ]
    for selector in close_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                locator.click(timeout=1500)
        except Exception:
            continue
    try:
        page.evaluate(
            """
            () => {
              const explicitPopupSelectors = [
                '#appView .powrModal.popupApp',
                '#appView .popupApp',
                '#appView .powr-popup',
                '#appView .powr-popup-overlay',
                '#appView .popupPowrMarkContainer',
                '#appView .popupBackground',
              ];
              for (const selector of explicitPopupSelectors) {
                for (const node of document.querySelectorAll(selector)) {
                  try { node.remove(); } catch (err) {}
                }
              }
              const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
              for (const node of candidates) {
                const text = (node.textContent || '').trim().toLowerCase();
                if (['cerrar', 'entendido', 'aceptar', 'estoy de acuerdo', 'close', 'x', '×'].includes(text)) {
                  try { node.click(); } catch (err) {}
                }
              }
              if (document.body) {
                document.body.style.overflow = 'auto';
                document.body.style.position = 'static';
              }
              const blockers = Array.from(document.querySelectorAll('body *')).filter((node) => {
                const style = window.getComputedStyle(node);
                return style && style.position === 'fixed' && parseInt(style.zIndex || '0', 10) >= 1000;
              });
              for (const node of blockers) {
                const text = (node.textContent || '').trim().toLowerCase();
                const className = (node.className || '').toString().toLowerCase();
                const id = (node.id || '').toString().toLowerCase();
                if (
                  text.includes('suscríbete') ||
                  text.includes('compras mínimas') ||
                  text.includes('modal') ||
                  text.includes('popup') ||
                  className.includes('powr') ||
                  className.includes('popupapp') ||
                  className.includes('popupbackground') ||
                  id.includes('powr') ||
                  id.includes('popup')
                ) {
                  try { node.remove(); } catch (err) {}
                }
              }
            }
            """
        )
    except Exception:
        pass



def collect_surface_insights_on_page(
    page,
    seed_url: str,
    host: str,
    *,
    max_scroll_steps: int = 24,
) -> tuple[list[str], list[str]]:
    links: list[str] = []
    pagination_urls: list[str] = []
    seen_links: set[str] = set()
    seen_pages: set[str] = set()
    page.goto(seed_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)
    clear_propartes_overlays(page)
    save_propartes_debug_snapshot(page=page, seed_url=seed_url, final_url=page.url, stage="initial")
    idle_rounds = 0
    last_count = 0
    scroll_steps = 0
    while scroll_steps < max_scroll_steps and idle_rounds < 4:
        try:
            hrefs = page.evaluate("Array.from(document.querySelectorAll('a[href]')).map((a) => a.href)")
        except Exception:
            hrefs = []
        current_count = 0
        for href in hrefs:
            if not isinstance(href, str) or not href.startswith('http'):
                continue
            normalized = canonical_url(href)
            if normalized in seen_links or not same_host(normalized, host) or ignored_url(normalized):
                continue
            seen_links.add(normalized)
            links.append(normalized)
            current_count += 1
        try:
            items = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('ngb-pagination a, ngb-pagination button, ngb-pagination li'))
                  .map((node) => ({
                    text: node.textContent ? node.textContent.trim() : '',
                    href: node.href ? node.href : (node.getAttribute('href') || ''),
                    aria: node.getAttribute('aria-label') ? node.getAttribute('aria-label') : '',
                  }))
                """
            )
        except Exception:
            items = []
        for item in items or []:
            href = item.get('href') if isinstance(item, dict) else ''
            text = normalize_text(item.get('text')) if isinstance(item, dict) else None
            aria = normalize_text(item.get('aria')) if isinstance(item, dict) else None
            if isinstance(href, str) and href.startswith('http'):
                normalized = canonical_url(href)
                if normalized not in seen_pages and same_host(normalized, host) and not ignored_url(normalized):
                    seen_pages.add(normalized)
                    pagination_urls.append(normalized)
            for value in (text, aria):
                if not value or not value.isdigit():
                    continue
                try:
                    page_number = int(value)
                except Exception:
                    continue
                candidate = build_propartes_page_url(seed_url, page_number)
                normalized = canonical_url(candidate)
                if normalized not in seen_pages and same_host(normalized, host) and not ignored_url(normalized):
                    seen_pages.add(normalized)
                    pagination_urls.append(normalized)
        if current_count <= last_count:
            idle_rounds += 1
        else:
            idle_rounds = 0
        last_count = current_count
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        try:
            page.mouse.wheel(0, 2500)
        except Exception:
            pass
        clear_propartes_overlays(page)
        save_propartes_debug_snapshot(
            page=page,
            seed_url=seed_url,
            final_url=page.url,
            stage=f"scroll-{scroll_steps + 1}",
        )
        try:
            page.wait_for_timeout(1100)
        except Exception:
            break
        scroll_steps += 1
    return links, pagination_urls

def collect_surface_insights(seed_url: str, host: str, *, max_scroll_steps: int = 24) -> tuple[list[str], list[str]]:
    sync_playwright = get_playwright()
    browser_path = detect_browser_executable()
    headless = not os.environ.get("PROPARTES_HEADED", "").strip().lower() in {"1", "true", "yes", "on"}
    links: list[str] = []
    pagination_urls: list[str] = []
    seen_links: set[str] = set()
    seen_pages: set[str] = set()
    try:
        with sync_playwright() as playwright:
            launch_kwargs = {"headless": headless}
            if browser_path:
                launch_kwargs["executable_path"] = browser_path
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto(seed_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            clear_propartes_overlays(page)
            save_propartes_debug_snapshot(page=page, seed_url=seed_url, final_url=page.url, stage="initial")
            idle_rounds = 0
            last_count = 0
            scroll_steps = 0
            while scroll_steps < max_scroll_steps and idle_rounds < 4:
                try:
                    hrefs = page.evaluate("Array.from(document.querySelectorAll('a[href]')).map((a) => a.href)")
                except Exception:
                    hrefs = []
                current_count = 0
                for href in hrefs:
                    if not isinstance(href, str) or not href.startswith('http'):
                        continue
                    normalized = canonical_url(href)
                    if normalized in seen_links or not same_host(normalized, host) or ignored_url(normalized):
                        continue
                    seen_links.add(normalized)
                    links.append(normalized)
                    current_count += 1
                try:
                    items = page.evaluate(
                        """
                        () => Array.from(document.querySelectorAll('ngb-pagination a, ngb-pagination button, ngb-pagination li'))
                          .map((node) => ({
                            text: node.textContent ? node.textContent.trim() : '',
                            href: node.href ? node.href : (node.getAttribute('href') || ''),
                            aria: node.getAttribute('aria-label') ? node.getAttribute('aria-label') : '',
                          }))
                        """
                    )
                except Exception:
                    items = []
                for item in items or []:
                    href = item.get('href') if isinstance(item, dict) else ''
                    text = normalize_text(item.get('text')) if isinstance(item, dict) else None
                    aria = normalize_text(item.get('aria')) if isinstance(item, dict) else None
                    if isinstance(href, str) and href.startswith('http'):
                        normalized = canonical_url(href)
                        if normalized not in seen_pages and same_host(normalized, host) and not ignored_url(normalized):
                            seen_pages.add(normalized)
                            pagination_urls.append(normalized)
                    for value in (text, aria):
                        if not value or not value.isdigit():
                            continue
                        try:
                            page_number = int(value)
                        except Exception:
                            continue
                        candidate = build_propartes_page_url(seed_url, page_number)
                        normalized = canonical_url(candidate)
                        if normalized not in seen_pages and same_host(normalized, host) and not ignored_url(normalized):
                            seen_pages.add(normalized)
                            pagination_urls.append(normalized)
                if current_count <= last_count:
                    idle_rounds += 1
                else:
                    idle_rounds = 0
                last_count = current_count
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                try:
                    page.mouse.wheel(0, 2500)
                except Exception:
                    pass
                clear_propartes_overlays(page)
                save_propartes_debug_snapshot(
                    page=page,
                    seed_url=seed_url,
                    final_url=page.url,
                    stage=f"scroll-{scroll_steps + 1}",
                )
                try:
                    page.wait_for_timeout(1100)
                except Exception:
                    break
                scroll_steps += 1
    except Exception:
        return [], []
    return links, pagination_urls


def collect_rendered_links(seed_url: str, host: str, *, max_scroll_steps: int = 24) -> list[str]:
    sync_playwright = get_playwright()
    browser_path = detect_browser_executable()
    headless = not os.environ.get("PROPARTES_HEADED", "").strip().lower() in {"1", "true", "yes", "on"}
    links: list[str] = []
    seen: set[str] = set()
    try:
        with sync_playwright() as playwright:
            launch_kwargs = {"headless": headless}
            if browser_path:
                launch_kwargs["executable_path"] = browser_path
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto(seed_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1800)
            idle_rounds = 0
            last_count = 0
            scroll_steps = 0
            while scroll_steps < max_scroll_steps and idle_rounds < 4:
                try:
                    hrefs = page.evaluate("Array.from(document.querySelectorAll('a[href]')).map((a) => a.href)")
                except Exception:
                    hrefs = []
                current_count = 0
                for href in hrefs:
                    if not isinstance(href, str) or not href.startswith("http"):
                        continue
                    normalized = canonical_url(href)
                    if normalized in seen or not same_host(normalized, host) or ignored_url(normalized):
                        continue
                    seen.add(normalized)
                    links.append(normalized)
                    current_count += 1
                if current_count <= last_count:
                    idle_rounds += 1
                else:
                    idle_rounds = 0
                last_count = current_count
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                try:
                    page.mouse.wheel(0, 2500)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(1200)
                except Exception:
                    break
                scroll_steps += 1
    except Exception:
        return []
    return links


def build_propartes_page_url(base_url: str, page_number: int) -> str:
    parsed = urlparse(base_url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_items = [(key, value) for key, value in query_items if key.lower() != "pagenumber"]
    next_items = [("pageNumber", str(page_number))]
    next_items.extend(filtered_items)
    encoded = urlencode(next_items, doseq=True)
    return parsed._replace(query=encoded).geturl()


def discover_pagination_urls(seed_url: str, host: str, *, max_scroll_steps: int = 4) -> list[str]:
    sync_playwright = get_playwright()
    browser_path = detect_browser_executable()
    headless = not os.environ.get("PROPARTES_HEADED", "").strip().lower() in {"1", "true", "yes", "on"}
    discovered: list[str] = []
    seen: set[str] = set()
    try:
        with sync_playwright() as playwright:
            launch_kwargs = {"headless": headless}
            if browser_path:
                launch_kwargs["executable_path"] = browser_path
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto(seed_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1600)
            scroll_steps = 0
            while scroll_steps < max_scroll_steps:
                try:
                    items = page.evaluate("""
                        () => Array.from(document.querySelectorAll('ngb-pagination a, ngb-pagination button, ngb-pagination li'))
                          .map((node) => ({
                            text: node.textContent ? node.textContent.trim() : '',
                            href: node.href ? node.href : (node.getAttribute('href') || ''),
                            aria: node.getAttribute('aria-label') ? node.getAttribute('aria-label') : '',
                            rel: node.getAttribute('rel') ? node.getAttribute('rel') : '',
                          }))
                    """)
                except Exception:
                    items = []
                for item in items or []:
                    href = item.get("href") if isinstance(item, dict) else ""
                    text = normalize_text(item.get("text")) if isinstance(item, dict) else None
                    aria = normalize_text(item.get("aria")) if isinstance(item, dict) else None
                    if isinstance(href, str) and href.startswith("http"):
                        normalized = canonical_url(href)
                        if normalized not in seen and same_host(normalized, host) and not ignored_url(normalized):
                            if category_like_url(normalized) or normalized == canonical_url(seed_url):
                                seen.add(normalized)
                                discovered.append(normalized)
                    if text and text.isdigit():
                        try:
                            page_number = int(text)
                        except Exception:
                            continue
                        candidate = build_propartes_page_url(seed_url, page_number)
                        normalized = canonical_url(candidate)
                        if normalized not in seen and same_host(normalized, host) and not ignored_url(normalized):
                            seen.add(normalized)
                            discovered.append(normalized)
                    if aria and aria.isdigit():
                        try:
                            page_number = int(aria)
                        except Exception:
                            continue
                        candidate = build_propartes_page_url(seed_url, page_number)
                        normalized = canonical_url(candidate)
                        if normalized not in seen and same_host(normalized, host) and not ignored_url(normalized):
                            seen.add(normalized)
                            discovered.append(normalized)
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                try:
                    page.mouse.wheel(0, 2500)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(900)
                except Exception:
                    break
                scroll_steps += 1
    except Exception:
        return []
    return discovered


def has_page_number(url: str) -> bool:
    parsed = urlparse(url)
    try:
        query_dict = dict(parse_qsl(parsed.query, keep_blank_values=True))
    except Exception:
        return False
    return "pagenumber" in {key.lower() for key in query_dict}
def pagination_candidates(url: str) -> list[str]:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "tienda.propartes.com":
        return []
    path = parsed.path.strip("/")
    if not path:
        return []
    segments = [segment for segment in path.split("/") if segment]
    root = segments[0].lower()
    if root not in PROPARTES_LISTING_ROOTS:
        return []

    query_dict = dict(parse_qsl(parsed.query, keep_blank_values=True))
    try:
        current_page = int(query_dict.get("pageNumber", "1"))
    except Exception:
        current_page = 1

    base_items = [(key, value) for key, value in query_dict.items() if key.lower() != "pagenumber"]
    candidates: list[str] = []
    for page_number in range(current_page + 1, PROPARTES_MAX_PAGE_NUMBER + 1):
        next_items = [("pageNumber", str(page_number))]
        next_items.extend(base_items)
        encoded = urlencode(next_items, doseq=True)
        candidates.append(parsed._replace(query=encoded).geturl())
    return candidates
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


def allowed_catalog_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() != PROPARTES_STORE_HOST:
        return False
    path = parsed.path.strip("/")
    if not path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False
    root = segments[0].lower()
    return root in PROPARTES_LISTING_ROOTS or root in PROPARTES_PRODUCT_ROOTS


def product_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    if default_product_like_url(url) or url_matches_any(url, EXTRA_PRODUCT_PATTERNS):
        return True
    parsed = urlparse(url)
    if parsed.netloc.lower() != "tienda.propartes.com":
        return False
    path = parsed.path.strip("/")
    if not path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return False
    root = segments[0].lower()
    tail = segments[-1].lower()
    lowered = url.lower()
    if root not in PROPARTES_PRODUCT_ROOTS:
        return False
    if tail in PROPARTES_NON_PRODUCT_TAILS or tail.endswith((".css", ".js", ".ico", ".png", ".jpg", ".jpeg", ".webp")):
        return False
    if "?pagenumber=" in lowered or "&pagenumber=" in lowered:
        return False
    if tail.startswith("page") or tail == root:
        return False
    return True


def category_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    if not allowed_catalog_url(url):
        return False
    return default_category_like_url(url) or url_matches_any(url, EXTRA_CATEGORY_PATTERNS)


def strip_tags(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = normalize_text(text)
    return text or None


def extract_propartes_description(html: str) -> str | None:
    patterns = [
        r'<div[^>]+class="woocommerce-product-details__short-description"[^>]*>(.*?)</div>',
        r'<div[^>]+id="tab-description"[^>]*>(.*?)<div[^>]+id="tab-reviews"',
        r'<div[^>]+class="woocommerce-Tabs-panel[^\"]*--description[^\"]*"[^>]*>(.*?)<div[^>]+class="woocommerce-Tabs-panel[^\"]*--reviews',
        r'<section[^>]+class="product-description[^"]*"[^>]*>(.*?)</section>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            text = strip_tags(match.group(1))
            if text:
                text = re.sub(r"^Description\s*", "", text, flags=re.IGNORECASE)
                return text
    return extract_meta_content(html, "description") or extract_meta_content(html, "og:description")


def extract_propartes_product_meta(html: str) -> tuple[str | None, str | None, str | None]:
    category_name = None
    subcategory_name = None
    brand = None

    category_match = re.search(
        r'<span class="posted_in detail-container">.*?<span class="detail-content">(.*?)</span></span>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if category_match:
        anchors = re.findall(r'>([^<]+)</a>', category_match.group(1), re.IGNORECASE | re.DOTALL)
        cleaned = [normalize_text(anchor) for anchor in anchors if normalize_text(anchor)]
        if cleaned:
            if len(cleaned) >= 2:
                category_name, subcategory_name = cleaned[-1], cleaned[0]
            else:
                category_name = cleaned[0]

    if not category_name or not subcategory_name:
        crumb_matches = [
            normalize_text(value)
            for value in re.findall(r'<a[^>]+(?:breadcrumb|crumb)[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
            if normalize_text(value)
        ]
        if crumb_matches:
            if not category_name and len(crumb_matches) >= 2:
                category_name = crumb_matches[-2]
            if not subcategory_name:
                subcategory_name = crumb_matches[-1]

    brand_match = re.search(
        r'\bMarca[:\s]+<a[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not brand_match:
        brand_match = re.search(r'\bMarca[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./ ]{2,})', html, re.IGNORECASE | re.DOTALL)
    if brand_match:
        brand = normalize_text(brand_match.group(1))

    return category_name, subcategory_name, brand


def extract_propartes_reference(html: str) -> str | None:
    patterns = [
        r'\bN[ºo]\s*de\s*parte[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./]+)',
        r'\bReferencia[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./]+)',
        r'\bSKU[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = normalize_text(match.group(1))
            if value:
                return value
    return None


def enrich_propartes_record(record: ProductRecord, html: str) -> ProductRecord:
    category_name, subcategory_name, brand = extract_propartes_product_meta(html)
    description = extract_propartes_description(html) or record.description
    reference = extract_propartes_reference(html) or record.reference
    sku = reference or record.sku
    image_url = extract_meta_content(html, "og:image") or record.image_url
    title = record.product_name or record.title
    lowered = " ".join(filter(None, [title, category_name, subcategory_name, description, brand])).lower()
    vehicle_scope = record.vehicle_scope or (
        "Autos" if any(token in lowered for token in ("auto", "automotriz", "vehiculo", "vehículo", "camioneta")) else None
    )
    searchable_tokens = build_searchable_tokens(
        title,
        brand,
        category_name,
        subcategory_name,
        description,
        reference,
        sku,
        vehicle_scope,
    )
    return replace(
        record,
        category_name=category_name or record.category_name,
        subcategory_name=subcategory_name or record.subcategory_name,
        brand=brand or record.brand,
        reference=reference,
        sku=sku,
        supplier_item_code=sku,
        description=description,
        vehicle_scope=vehicle_scope,
        image_url=image_url,
        searchable_tokens=searchable_tokens or record.searchable_tokens,
    )


def build_propartes_record(
    *,
    url: str,
    html: str,
    source_page_url: str,
    infer_match_type: Callable[[str | None, str | None, str | None, str | None], tuple[str, str, bool]],
) -> ProductRecord | None:
    title = extract_page_title(html) or extract_meta_content(html, "og:title") or extract_meta_content(html, "twitter:title")
    if not title:
        return None
    category_name, subcategory_name, brand = extract_propartes_product_meta(html)
    description = extract_propartes_description(html)
    image_url = extract_meta_content(html, "og:image")
    reference = extract_propartes_reference(html)
    sku = reference
    lowered = " ".join(filter(None, [title, category_name, subcategory_name, description, brand])).lower()
    vehicle_scope = "Autos" if any(token in lowered for token in ("auto", "automotriz", "vehiculo", "vehículo", "camioneta")) else None
    match_type, confidence, manual = infer_match_type(title, category_name, description, reference)
    return ProductRecord(
        item_type="product",
        provider_type="product_catalog",
        product_name=title,
        product_url=url,
        detail_url=url,
        category_name=category_name,
        subcategory_name=subcategory_name,
        brand=brand,
        reference=reference,
        sku=sku,
        supplier_item_code=sku,
        description=description,
        vehicle_scope=vehicle_scope,
        image_url=image_url,
        source_page_url=source_page_url,
        page_number=guess_page_number(source_page_url),
        match_type=match_type,
        match_confidence=confidence,
        requires_manual_confirmation=manual,
        searchable_tokens=build_searchable_tokens(
            title,
            brand,
            category_name,
            subcategory_name,
            description,
            reference,
            sku,
            vehicle_scope,
        ),
    )


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("catalog_root_url") or metadata.get("website") or "")).netloc.lower()
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
    records: list[ProductRecord] = []
    notes = [AUTOS_ONLY_NOTE]

    sync_playwright = get_playwright()
    browser_path = detect_browser_executable()
    headless = not os.environ.get("PROPARTES_HEADED", "").strip().lower() in {"1", "true", "yes", "on"}
    with sync_playwright() as playwright:
        launch_kwargs = {"headless": headless}
        if browser_path:
            launch_kwargs["executable_path"] = browser_path
        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
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
            product_hint = product_like_url(final_url)
            product_records = product_from_json_ld(
                url=final_url,
                page_title=page_title,
                description=meta_description,
                image_url=meta_image,
                source_page_url=source_page_url,
                json_ld_nodes=json_ld_nodes,
                infer_match_type=infer_match_type,
            ) if product_hint else []

            if product_records:
                product_records = [enrich_propartes_record(record, html) for record in product_records]
            if product_hint and not product_records:
                fallback = build_propartes_record(
                    url=final_url,
                    html=html,
                    source_page_url=source_page_url,
                    infer_match_type=infer_match_type,
                )
                if not fallback:
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

            if category_like_url(final_url) and not product_hint:
                render_scroll_steps = 2 if has_page_number(final_url) else 6
                surface_links, paginated_urls = collect_surface_insights_on_page(page, final_url, host, max_scroll_steps=render_scroll_steps)
                for link in surface_links:
                    if link in visited or link in seen_queue:
                        continue
                    if not same_host(link, host) or ignored_url(link):
                        continue
                    if product_like_url(link) or category_like_url(link):
                        queue.append((link, final_url))
                        seen_queue.add(link)

                if not has_page_number(final_url):
                    if not paginated_urls:
                        paginated_urls = pagination_candidates(final_url)
                    for paginated_url in paginated_urls:
                        if paginated_url in visited or paginated_url in seen_queue:
                            continue
                        if not same_host(paginated_url, host) or ignored_url(paginated_url):
                            continue
                        queue.append((paginated_url, final_url))
                        seen_queue.add(paginated_url)

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
        page.close()
        context.close()
        browser.close()


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












