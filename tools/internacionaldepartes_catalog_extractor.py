#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    dedupe_records,
    extract_meta_content,
    extract_page_title,
    iter_json_ld_nodes,
    latest_snapshot_json,
    load_json,
    parse_json_ld_blocks,
    parse_product_fallback,
    product_from_json_ld,
    provider_paths,
    same_host,
    slug_to_words,
    write_snapshot_bundle,
)

PROVIDER_ID = "internacionaldepartes"
DISPLAY_NAME = "Internacional de Partes"
LISTING_URL = "https://internacionaldepartes.com/productos"
COUNT_SELECTOR = "#results-count"
GRID_SELECTOR = "#product-grid"
PAGINATION_SELECTOR = "#pagination"
PRODUCT_LINK_SELECTOR = '#product-grid a[href*="/productos/"]'
HEADLESS_ENV = f"{PROVIDER_ID.upper()}_HEADED"
BROWSER_PATH_ENV = "PLAYWRIGHT_BROWSER_PATH"
EXCLUDE_KEYWORDS = ()

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



def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/internacionaldepartes_catalog_extractor.py`."
        ) from exc
    return sync_playwright


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = str(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _match_key(value: str) -> str:
    text = _clean(value).casefold()
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _first_non_empty(lines: list[str], start: int) -> str:
    for value in lines[start:]:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return ""


def _extract_label_value(lines: list[str], label: str) -> str:
    target = _match_key(label)
    for index, value in enumerate(lines):
        cleaned = _clean(value)
        if not cleaned:
            continue
        normalized = _match_key(cleaned)
        if normalized == target:
            return _first_non_empty(lines, index + 1)
        if normalized.startswith(f"{target}:") or normalized.startswith(f"{target} "):
            suffix = cleaned[len(label):].strip(" :-\t")
            if suffix:
                return suffix
            return _first_non_empty(lines, index + 1)
    return ""


def _extract_first_price(text: str) -> str:
    match = re.search(r"\$\s*[\d\.]+(?:,[\d]{2})?", text)
    if match:
        return _clean(match.group(0))
    return ""


def _extract_stock(text: str) -> str:
    match = re.search(r"Stock(?:\s+disponible)?\s*\(?\s*(\d+)\s*\)?", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _extract_detail_text(page) -> str:
    try:
        return _clean(page.locator("main").inner_text(timeout=8000))
    except Exception:
        try:
            return _clean(page.locator("body").inner_text(timeout=8000))
        except Exception:
            return ""


def _detect_browser_executable() -> str | None:
    configured = os.environ.get(BROWSER_PATH_ENV, "").strip()
    if configured:
        return configured
    for candidate in ("/usr/bin/chromium-browser", "/usr/bin/chromium", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "chromium-browser", "chromium", "google-chrome", "google-chrome-stable"):
        resolved = shutil.which(candidate) if not candidate.startswith("/") else candidate
        if resolved and Path(resolved).exists():
            return resolved
    return None


def _log(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _dismiss_popups(page) -> None:
    selectors = (
        "button:has-text('Aceptar')",
        "button:has-text('Acepto')",
        "button:has-text('Entendido')",
        "button:has-text('Cerrar')",
        "button:has-text('Close')",
        "button:has-text('OK')",
        "[aria-label*='close' i]",
        "[aria-label*='cerrar' i]",
        "[id*='cookie' i] button",
        "[class*='cookie' i] button",
        "[class*='modal' i] button",
        "[class*='popup' i] button",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=500):
                locator.click(timeout=1200, force=True)
                page.wait_for_timeout(150)
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _extract_results_count(page) -> int | None:
    try:
        text = _clean(page.locator(COUNT_SELECTOR).inner_text(timeout=4000))
    except Exception:
        return None
    match = re.search(r"(\d[\d\.,]*)", text)
    if not match:
        return None
    value = match.group(1).replace(".", "").replace(",", "")
    try:
        return int(value)
    except ValueError:
        return None


def _discover_total_pages(page) -> int:
    try:
        values = page.locator(f"{PAGINATION_SELECTOR} button, {PAGINATION_SELECTOR} a").evaluate_all(
            "elements => elements.map((element) => (element.getAttribute('data-page') || element.textContent || '').trim()).filter(Boolean)"
        )
    except Exception:
        values = []
    numbers: list[int] = []
    for value in values or []:
        cleaned = _clean(value)
        if cleaned.isdigit():
            numbers.append(int(cleaned))
    return max(numbers) if numbers else 1


def _listing_signature(page) -> str:
    try:
        hrefs = page.evaluate(
            """() => {
              const grid = document.querySelector('#product-grid');
              if (!grid) return [];
              const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              return Array.from(grid.querySelectorAll('a[href]'))
                .filter((anchor) => {
                  const card = anchor.closest('article, li, .product, .product-item, .grid-item, .card, .woocommerce-loop-product, div') || anchor;
                  return isVisible(card);
                })
                .map((anchor) => anchor.href || anchor.getAttribute('href') || '')
                .filter((href) => href.includes('/productos/'));
            }"""
        )
    except Exception:
        hrefs = []
    normalized = [canonical_url(href) for href in hrefs if "/productos/" in href.lower()]
    return "|".join(normalized)


def _listing_cards(page, listing_page_number: int) -> list[dict[str, Any]]:
    try:
        raw_cards = page.evaluate(
            """() => {
              const grid = document.querySelector('#product-grid');
              if (!grid) return [];
              const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              return Array.from(grid.querySelectorAll('a[href]'))
                .filter((anchor) => {
                  const card = anchor.closest('article, li, .product, .product-item, .grid-item, .card, .woocommerce-loop-product, div') || anchor;
                  return isVisible(card);
                })
                .map((anchor, index) => {
                  const href = anchor.getAttribute('href') || '';
                  const card = anchor.closest('article, li, .product, .product-item, .grid-item, .card, .woocommerce-loop-product, div') || anchor;
                  const image = card ? card.querySelector('img') : null;
                  return {
                    href,
                    text: (card?.innerText || anchor.innerText || anchor.textContent || '').trim(),
                    title: (anchor.getAttribute('title') || card?.getAttribute('title') || '').trim(),
                    aria: (anchor.getAttribute('aria-label') || card?.getAttribute('aria-label') || '').trim(),
                    image: image ? (image.currentSrc || image.src || '') : '',
                    alt: image ? (image.alt || '') : '',
                    brand: card?.getAttribute('data-brand') || card?.dataset?.brand || '',
                    category: card?.getAttribute('data-category') || card?.dataset?.category || '',
                    sku: card?.getAttribute('data-sku') || card?.dataset?.sku || '',
                    price: card?.getAttribute('data-price') || card?.dataset?.price || '',
                    index,
                  };
                });
            }"""
        )
    except Exception:
        raw_cards = []

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_cards or []:
        href = _clean(raw.get("href"))
        if not href:
            continue
        normalized = canonical_url(href)
        if "/productos/" not in normalized.lower():
            continue
        if normalized.rstrip("/") == LISTING_URL.rstrip("/"):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        cards.append(
            {
                "detail_url": normalized,
                "listing_page_number": listing_page_number,
                "card_text": _clean(raw.get("text")),
                "card_title": _clean(raw.get("title") or raw.get("aria") or raw.get("alt") or raw.get("text")),
                "card_brand": _clean(raw.get("brand")),
                "card_category": _clean(raw.get("category")),
                "card_sku": _clean(raw.get("sku")),
                "card_price": _clean(raw.get("price")),
                "image_url": _clean(raw.get("image")),
            }
        )
    return cards


def _click_page(page, target_page: int) -> bool:
    selectors = [
        f'{PAGINATION_SELECTOR} button[data-page="{target_page}"]',
        f'{PAGINATION_SELECTOR} a[data-page="{target_page}"]',
        f'{PAGINATION_SELECTOR} button:has-text("{target_page}")',
        f'{PAGINATION_SELECTOR} a:has-text("{target_page}")',
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count():
                locator.scroll_into_view_if_needed(timeout=2000)
                locator.click(timeout=5000, force=True)
                return True
        except Exception:
            continue
    try:
        return bool(
            page.evaluate(
                """(pageNumber) => {
                  const candidates = Array.from(document.querySelectorAll('#pagination button, #pagination a'));
                  const match = candidates.find((element) => {
                    const dataPage = (element.getAttribute('data-page') || '').trim();
                    const text = (element.textContent || '').trim();
                    return dataPage === String(pageNumber) || text === String(pageNumber);
                  });
                  if (!match) return false;
                  match.click();
                  return true;
                }""",
                target_page,
            )
        )
    except Exception:
        return False


def _wait_for_listing_change(page, previous_signature: str, timeout_ms: int = 20000) -> None:
    page.wait_for_function(
        """(previousSignature) => {
          const grid = document.querySelector('#product-grid');
          if (!grid) return false;
          const isVisible = (element) => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const current = Array.from(grid.querySelectorAll('a[href]'))
            .filter((anchor) => {
              const card = anchor.closest('article, li, .product, .product-item, .grid-item, .card, .woocommerce-loop-product, div') || anchor;
              return isVisible(card);
            })
            .map((element) => element.href || element.getAttribute('href') || '')
            .filter((href) => href.includes('/productos/'))
            .join('|');
          return current && current !== previousSignature;
        }""",
        arg=previous_signature,
        timeout=timeout_ms,
    )

def _infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, category_name, description, reference])).lower()
    if any(token in allowed_text for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", True
    if reference:
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def _listing_fallback_record(*, detail_url: str, listing_page_url: str, listing_card: dict[str, Any]) -> ProductRecord | None:
    title = listing_card.get("card_title") or listing_card.get("card_text") or slug_to_words(Path(urlparse(detail_url).path).name)
    if not title:
        return None
    description = listing_card.get("card_text") or listing_card.get("card_price") or None
    brand = listing_card.get("card_brand") or None
    category_name = listing_card.get("card_category") or None
    reference = listing_card.get("card_sku") or None
    match_type, confidence, manual = _infer_match_type(title, category_name, description, reference)
    return ProductRecord(
        item_type="product",
        provider_type="product_catalog",
        product_name=title,
        detail_url=detail_url,
        product_url=detail_url,
        category_name=category_name,
        brand=brand,
        reference=reference,
        sku=reference,
        supplier_item_code=reference,
        description=description,
        image_url=listing_card.get("image_url") or None,
        source_page_url=listing_page_url,
        page_number=int(listing_card.get("listing_page_number") or 1),
        match_type=match_type,
        match_confidence=confidence,
        requires_manual_confirmation=manual,
        searchable_tokens=build_searchable_tokens(title, brand, category_name, description, reference),
    )


def _detail_record_from_page(
    *,
    detail_url: str,
    listing_page_url: str,
    listing_page_number: int,
    listing_card: dict[str, Any],
    page,
) -> tuple[ProductRecord | None, str | None]:
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_load_state("networkidle", timeout=120000)
        page.wait_for_selector("h1", timeout=15000)
        _dismiss_popups(page)
    except Exception as exc:
        fallback = _listing_fallback_record(detail_url=detail_url, listing_page_url=listing_page_url, listing_card=listing_card)
        if fallback is not None:
            fallback.page_number = listing_page_number
            fallback.source_page_url = listing_page_url
            return fallback, f"detail_navigation_failed: {exc}"
        return None, f"detail_navigation_failed: {exc}"

    try:
        html = page.content()
    except Exception as exc:
        html = ""
        html_error = f"detail_html_failed: {exc}"
    else:
        html_error = None

    main_text = _extract_detail_text(page)
    page_title = extract_page_title(html) if html else None
    meta_description = extract_meta_content(html, "description") if html else None
    meta_image = extract_meta_content(html, "og:image") if html else None
    json_ld_nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)] if html else []
    product_records = product_from_json_ld(
        url=detail_url,
        page_title=page_title,
        description=meta_description,
        image_url=meta_image,
        source_page_url=listing_page_url,
        json_ld_nodes=json_ld_nodes,
        infer_match_type=_infer_match_type,
    )
    record = product_records[0] if product_records else parse_product_fallback(
        url=detail_url,
        html=html,
        source_page_url=listing_page_url,
        category_only_mode=False,
        infer_match_type=_infer_match_type,
    )

    if record is None:
        record = _listing_fallback_record(detail_url=detail_url, listing_page_url=listing_page_url, listing_card=listing_card)
        if record is None:
            return None, html_error or "detail_parse_failed"

    lines = [line.strip() for line in main_text.splitlines() if line.strip()]
    visible_title = _clean(page.locator("h1").first.inner_text(timeout=5000)) if page.locator("h1").count() else ""
    visible_brand = _extract_label_value(lines, "MARCA COMPATIBLE") or _extract_label_value(lines, "MARCA")
    visible_category = _extract_label_value(lines, "CATEGORIA") or _extract_label_value(lines, "CATEGORÍA")
    visible_reference = _extract_label_value(lines, "REFERENCIA (SKU)") or _extract_label_value(lines, "REFERENCIA")
    visible_internal_id = _extract_label_value(lines, "IDENTIFICADOR INTERNO")
    visible_stock = _extract_label_value(lines, "STOCK") or _extract_stock(main_text)
    visible_price = _extract_first_price(main_text)
    visible_vehicle_scope = "Autos" if any(token in _match_key(main_text) for token in VEHICLE_TOKENS) or "auto" in _match_key(main_text) else None

    if visible_title:
        record.product_name = visible_title
    if visible_brand and not record.brand:
        record.brand = visible_brand
    if visible_category and not record.category_name:
        record.category_name = visible_category
    if visible_reference:
        record.reference = visible_reference
        record.sku = visible_reference
    if visible_internal_id:
        record.supplier_item_code = visible_internal_id
    if visible_stock and record.description and "stock" not in _match_key(record.description):
        record.description = _clean(f"{record.description}. Stock disponible ({visible_stock}).")
    if visible_price and record.description and visible_price not in record.description:
        record.description = _clean(f"{record.description}. Precio {visible_price} COP.")
    if not record.description:
        record.description = meta_description or listing_card.get("card_text") or main_text or None
    if meta_description and record.description and meta_description not in record.description:
        record.description = _clean(f"{meta_description} {record.description}")
    if visible_vehicle_scope and not record.vehicle_scope:
        record.vehicle_scope = visible_vehicle_scope
    if not record.image_url:
        record.image_url = meta_image or listing_card.get("image_url") or None
    if record.category_name and record.subcategory_name is None:
        record.subcategory_name = visible_title or record.product_name
    if record.brand is None and listing_card.get("card_brand"):
        record.brand = listing_card.get("card_brand")
    if record.reference is None and listing_card.get("card_sku"):
        record.reference = listing_card.get("card_sku")
        record.sku = listing_card.get("card_sku")
    if record.sku is None and record.reference:
        record.sku = record.reference
    if record.supplier_item_code is None and record.sku:
        record.supplier_item_code = record.sku
    if not record.vehicle_scope and any(token in _match_key(record.description or "") for token in VEHICLE_TOKENS):
        record.vehicle_scope = "Autos"

    title_for_tokens = record.product_name or visible_title or listing_card.get("card_title")
    record.searchable_tokens = build_searchable_tokens(
        title_for_tokens,
        record.brand,
        record.category_name,
        record.subcategory_name,
        record.description,
        record.reference,
        record.sku,
        record.vehicle_scope,
        visible_price,
        visible_stock,
        visible_internal_id,
    )
    record.detail_url = detail_url
    record.product_url = detail_url
    record.source_page_url = listing_page_url
    record.page_number = listing_page_number
    record.match_type, record.match_confidence, record.requires_manual_confirmation = _infer_match_type(
        record.product_name,
        record.category_name,
        record.description,
        record.reference,
    )
    record.requires_manual_confirmation = True
    return record, html_error


def run_extractor(snapshot_date: str | None = None) -> dict[str, Any]:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    snapshot_day = snapshot_date or date.today().isoformat()
    listing_root = canonical_url(str(metadata.get("catalog_root_url") or LISTING_URL))
    listing_host = urlparse(listing_root).netloc.lower()
    visible_total = 0
    total_pages = 1
    products: list[ProductRecord] = []
    listing_pages: list[dict[str, Any]] = []
    detail_failures: list[dict[str, Any]] = []
    missing_samples: list[dict[str, Any]] = []
    notes = [MANUAL_NOTE, "Extraction follows the paginated product catalog directly and captures every visible product without filtering by vehicle type."]
    seen_urls: set[str] = set()

    sync_playwright = get_playwright()
    browser_path = _detect_browser_executable()
    headless = not _env_flag(HEADLESS_ENV, default=False)
    with sync_playwright() as p:
        browser_kwargs: dict[str, Any] = {"headless": headless}
        if browser_path:
            browser_kwargs["executable_path"] = browser_path
        browser = p.chromium.launch(**browser_kwargs)
        context = browser.new_context(viewport={"width": 1600, "height": 2400}, locale="es-CO")
        listing_page = context.new_page()
        detail_page = context.new_page()
        try:
            listing_page.goto(listing_root, wait_until="domcontentloaded", timeout=120000)
            listing_page.wait_for_timeout(1500)
            _dismiss_popups(listing_page)
            listing_page.wait_for_selector(GRID_SELECTOR, timeout=30000)
            listing_page.wait_for_selector(COUNT_SELECTOR, timeout=30000)
            visible_total = _extract_results_count(listing_page) or 0
            total_pages = _discover_total_pages(listing_page)
            current_signature = _listing_signature(listing_page)
            _log("listing_initialized", visible_total=visible_total, total_pages=total_pages, signature=current_signature[:200])

            for page_number in range(1, total_pages + 1):
                _dismiss_popups(listing_page)
                listing_page.wait_for_selector(GRID_SELECTOR, timeout=30000)
                page_cards = _listing_cards(listing_page, page_number)
                if not page_cards:
                    detail_failures.append({"page_number": page_number, "reason": "empty_listing_page", "listing_url": listing_root})
                listing_pages.append(
                    {
                        "page_number": page_number,
                        "listing_url": listing_root,
                        "cards_seen": len(page_cards),
                        "detail_urls": [card["detail_url"] for card in page_cards],
                        "signature": _listing_signature(listing_page),
                    }
                )
                _log("listing_page_scanned", page_number=page_number, cards_seen=len(page_cards))

                for card in page_cards:
                    detail_url = card["detail_url"]
                    if detail_url in seen_urls:
                        continue
                    seen_urls.add(detail_url)
                    record, failure = _detail_record_from_page(
                        detail_url=detail_url,
                        listing_page_url=listing_root,
                        listing_page_number=page_number,
                        listing_card=card,
                        page=detail_page,
                    )
                    if record is not None:
                        products.append(record)
                    else:
                        detail_failures.append(
                            {
                                "page_number": page_number,
                                "detail_url": detail_url,
                                "reason": failure or "detail_record_missing",
                                "card_title": card.get("card_title"),
                            }
                        )

                if page_number < total_pages:
                    next_page = page_number + 1
                    previous_signature = current_signature
                    if not _click_page(listing_page, next_page):
                        detail_failures.append(
                            {
                                "page_number": page_number,
                                "detail_url": None,
                                "reason": f"pagination_button_not_found_for_page_{next_page}",
                            }
                        )
                        break
                    _wait_for_listing_change(listing_page, previous_signature)
                    listing_page.wait_for_timeout(800)
                    _dismiss_popups(listing_page)
                    current_signature = _listing_signature(listing_page)
        finally:
            try:
                detail_page.close()
            except Exception:
                pass
            try:
                listing_page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    deduped_products = dedupe_records(products, EXCLUDE_KEYWORDS)
    product_urls = {record.detail_url or record.product_url for record in deduped_products if record.detail_url or record.product_url}
    listing_urls = {url for page in listing_pages for url in page.get("detail_urls", [])}
    missing_urls = sorted(url for url in listing_urls if url not in product_urls)
    if missing_urls:
        for detail_url in missing_urls[:10]:
            sample = next((item for item in detail_failures if item.get("detail_url") == detail_url), None)
            missing_samples.append(
                {
                    "detail_url": detail_url,
                    "reason": sample.get("reason") if sample else "not_returned_in_products",
                }
            )

    expected_count = visible_total or len(listing_urls)
    notes.append(f"Visible product count reported by site: {visible_total or 'unknown'}.")
    notes.append(f"Listing detail URLs discovered: {len(listing_urls)}.")
    notes.append(f"Final deduped product count: {len(deduped_products)}.")
    if missing_samples:
        notes.append(f"Missing examples: {', '.join(sample['detail_url'] for sample in missing_samples[:3])}.")
        notes.append("Probable cause: pagination navigation or detail-page parsing dropped one or more products on those URLs.")

    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=deduped_products,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    extracted_path = write_snapshot_bundle(
        output_root=output_root,
        snapshot_date=snapshot_day,
        payload=payload,
        products=deduped_products,
    )
    snapshot_dir = extracted_path.parent
    (snapshot_dir / "listing_evidence.json").write_text(
        json.dumps(
            {
                "provider_id": PROVIDER_ID,
                "snapshot_date": snapshot_day,
                "listing_url": listing_root,
                "visible_total": visible_total,
                "total_pages": total_pages,
                "pages": listing_pages,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (snapshot_dir / "detail_failures.json").write_text(json.dumps(detail_failures, indent=2, ensure_ascii=False), encoding="utf-8")
    (snapshot_dir / "missing_products.json").write_text(json.dumps(missing_samples, indent=2, ensure_ascii=False), encoding="utf-8")

    status = "completed"
    if expected_count and len(deduped_products) < expected_count:
        missing_count = expected_count - len(deduped_products)
        if missing_count > max(10, int(expected_count * 0.02)):
            status = "failed"
    return {
        "status": status,
        "provider_id": PROVIDER_ID,
        "snapshot_path": str(extracted_path),
        "snapshot_dir": str(snapshot_dir),
        "visible_total": visible_total,
        "total_pages": total_pages,
        "listing_urls": len(listing_urls),
        "products": len(deduped_products),
        "expected_count": expected_count,
        "missing_count": max(0, expected_count - len(deduped_products)),
        "missing_samples": missing_samples,
        "detail_failures": len(detail_failures),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Live catalog extractor for {PROVIDER_ID}.")
    parser.add_argument("--snapshot-date", default=None)
    args = parser.parse_args(argv)
    result = run_extractor(snapshot_date=args.snapshot_date)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())









