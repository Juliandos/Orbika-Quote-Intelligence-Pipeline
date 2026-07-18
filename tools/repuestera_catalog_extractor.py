#!/usr/bin/env python3
"""Read-only Repuestera catalog extractor for the live product listing."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import time
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

REPUSTERA_ROOT_URL = "https://repuestera.com.co/shop/"
REPUSTERA_LISTING_URL = REPUSTERA_ROOT_URL + "?jsf=jet-engine:productos&pagenum={page_number}"
DEFAULT_OUTPUT_DIR = Path("supplier_catalog/providers/repuestera/snapshots")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
CATEGORY_ITEM_START_PATTERN = re.compile(
    r'<div class="jet-woo-categories__item[^"]*"[^>]*>',
    re.IGNORECASE,
)
ITEM_START_PATTERN = re.compile(
    r'<div class="jet-listing-grid__item\b[^>]*data-post-id="(?P<post_id>\d+)"[^>]*>',
    re.IGNORECASE,
)
PAGE_CONFIG_PATTERN = re.compile(
    r'"jet-engine":\{"productos":\{"found_posts":(?P<found>\d+),"max_num_pages":(?P<pages>\d+),"page":(?P<page>\d+)\}\}'
)
PRODUCT_CONTAINER_SELECTOR = "#productos .jet-listing-grid__items"
PRODUCT_CARD_SELECTOR = "#productos .jet-listing-grid__item[data-post-id]"
MODAL_CLOSE_SELECTORS = (
    ".elementor-popup-modal .dialog-close-button",
    ".elementor-popup-modal .eicon-close",
    ".dialog-close-button",
    ".eicon-close",
    ".jet-popup__close-button",
    ".jet-popup__close-btn",
    "button:has-text('x')",
    "button:has-text('X')",
    "button:has-text('Cerrar')",
    "button:has-text('Close')",
    "[aria-label*='close' i]",
    "[aria-label*='cerrar' i]",
    "[class*='close' i]",
)


@dataclass
class CatalogCategory:
    category_name: str
    category_url: str
    image_url: str | None = None


@dataclass
class RepuesteraProduct:
    post_id: str
    reference: str | None
    product_name: str
    brand: str | None
    category_name: str | None
    detail_url: str
    image_url: str | None
    image_alt: str | None
    page_number: int
    source_page_url: str
    searchable_tokens: list[str] = field(default_factory=list)
    match_type: str = "manual_confirmation_required"
    match_confidence: str = "low"


def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/repuestera_catalog_extractor.py`."
        ) from exc
    return sync_playwright


def detect_browser_executable() -> str | None:
    env_path = os.environ.get("REPUESTERA_BROWSER_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    for candidate in (
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "msedge",
    ):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def normalize_text(value: str | None) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def html_attr(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"""\b{re.escape(name)}\s*=\s*(?:\"([^"]*)\"|'([^']*)'|([^\s>]+))""",
        attrs,
        re.IGNORECASE,
    )
    if not match:
        return None
    return unescape(next(group for group in match.groups() if group is not None))


def fetch_html(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()
        return raw.decode(charset or "utf-8", errors="replace")


def build_catalog_page_url(page_number: int) -> str:
    if page_number <= 1:
        return REPUSTERA_ROOT_URL
    return REPUSTERA_LISTING_URL.format(page_number=page_number)


def parse_page_config(html: str) -> tuple[int, int]:
    match = PAGE_CONFIG_PATTERN.search(html)
    if match:
        return int(match.group("found")), int(match.group("pages"))
    return 0, 1


def parse_max_page_number(html: str) -> int:
    """Backward-compatible helper for callers that only need page count."""
    match = PAGE_CONFIG_PATTERN.search(html)
    if match:
        return int(match.group("pages"))
    signals = [int(value) for value in re.findall(r"data-pages=[\"'](\d+)[\"']", html, re.IGNORECASE)]
    signals.extend(int(value) for value in re.findall(r"pagenum=(\d+)", html, re.IGNORECASE))
    return max(signals, default=1)


def build_searchable_tokens(*values: str | None) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for value in values:
        if not value:
            continue
        for token in re.split(r"[^A-Za-z0-9ÃÃ‰ÃÃ“ÃšÃœÃ‘Ã¡Ã©Ã­Ã³ÃºÃ¼Ã±]+", value):
            normalized = normalize_text(token).lower()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            tokens.append(normalized)
    return tokens


def infer_match(reference: str | None, product_name: str, brand: str | None, category_name: str | None) -> tuple[str, str]:
    if reference:
        return "exact_reference", "high"
    if product_name and (brand or category_name):
        return "category_only", "medium"
    return "manual_confirmation_required", "low"


def parse_category_carousel(html: str) -> list[CatalogCategory]:
    categories: list[CatalogCategory] = []
    seen: set[str] = set()
    starts = list(CATEGORY_ITEM_START_PATTERN.finditer(html))
    for index, match in enumerate(starts):
        start = match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        block = html[start:end]
        title_match = re.search(
            r'<a href="([^"]+)" class="jet-woo-category-title__link"[^>]*>(.*?)</a>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        category_url = unescape(title_match.group(1))
        category_name = normalize_text(title_match.group(2))
        if not category_name or category_url in seen:
            continue
        image_match = re.search(r"<img\b([^>]*)>", block, re.IGNORECASE | re.DOTALL)
        image_url = html_attr(image_match.group(1), "src") if image_match else None
        categories.append(
            CatalogCategory(
                category_name=category_name,
                category_url=category_url,
                image_url=image_url,
            )
        )
        seen.add(category_url)
    return categories


def close_registration_modal(page) -> bool:
    for selector in MODAL_CLOSE_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=500):
                locator.click(timeout=1500, force=True)
                page.wait_for_timeout(250)
                return True
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return False


def wait_for_product_grid(page, previous_first_url: str) -> None:
    page.wait_for_function(
        """
        ({ containerSelector, previous }) => {
          const wrappers = Array.from(document.querySelectorAll(containerSelector));
          const wrapper = wrappers.find((el) => el.getClientRects().length > 0);
          if (!wrapper) return false;
          const cards = Array.from(wrapper.querySelectorAll('.jet-listing-grid__item[data-post-id]')).filter((el) => el.getClientRects().length > 0);
          if (!cards.length) return false;
          const link = cards[0].querySelector('a.jet-listing-dynamic-image__link');
          if (!link) return false;
          const href = link.href || link.getAttribute('href') || '';
          return href && href !== previous;
        }
        """,
        arg={"containerSelector": PRODUCT_CONTAINER_SELECTOR, "previous": previous_first_url},
        timeout=15000,
    )
    last_count = -1
    stable_rounds = 0
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            count = page.evaluate(
                """
                (containerSelector) => {
                  const wrappers = Array.from(document.querySelectorAll(containerSelector));
                  const wrapper = wrappers.find((el) => el.getClientRects().length > 0);
                  if (!wrapper) return 0;
                  return Array.from(wrapper.querySelectorAll('.jet-listing-grid__item[data-post-id]'))
                    .filter((el) => el.getClientRects().length > 0).length;
                }
                """,
                PRODUCT_CONTAINER_SELECTOR,
            )
        except Exception:
            count = 0
        if count > 0 and count == last_count:
            stable_rounds += 1
            if stable_rounds >= 2:
                break
        else:
            stable_rounds = 0
            last_count = count
        page.wait_for_timeout(500)
def parse_product_cards(
    html: str,
    source_page_url: str,
    page_number: int,
) -> list[RepuesteraProduct]:
    """Parse product cards for offline compatibility tests and HTTP fallbacks."""
    starts = list(ITEM_START_PATTERN.finditer(html))
    products: list[RepuesteraProduct] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        block = html[match.start():end]
        link_tag = re.search(
            r'<a\b([^>]*class="[^"]*jet-listing-dynamic-image__link[^"]*"[^>]*)>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not link_tag:
            link_tag = re.search(r'<a\b([^>]+)>', block, re.IGNORECASE | re.DOTALL)
        detail_url = canonical_url(html_attr(link_tag.group(1), "href") or "") if link_tag else ""
        if not detail_url:
            continue
        image_match = re.search(r"<img\b([^>]*)>", block, re.IGNORECASE | re.DOTALL)
        image_url = html_attr(image_match.group(1), "src") if image_match else None
        image_alt = html_attr(image_match.group(1), "alt") if image_match else None
        fields = [
            normalize_text(value)
            for value in re.findall(
                r'<(?:div|span)[^>]+class="[^"]*jet-listing-dynamic-field__content[^"]*"[^>]*>(.*?)</',
                block,
                re.IGNORECASE | re.DOTALL,
            )
        ]
        terms = [
            normalize_text(value)
            for value in re.findall(
                r'<[^>]+class="[^"]*jet-listing-dynamic-terms__link[^"]*"[^>]*>(.*?)</',
                block,
                re.IGNORECASE | re.DOTALL,
            )
        ]
        reference = fields[0] if fields else None
        product_name = fields[1] if len(fields) >= 2 else (image_alt or reference or "")
        brand = fields[2] if len(fields) >= 3 else (terms[0] if terms else None)
        category_name = fields[3] if len(fields) >= 4 else (terms[1] if len(terms) >= 2 else None)
        match_type, match_confidence = infer_match(reference, product_name, brand, category_name)
        products.append(
            RepuesteraProduct(
                post_id=match.group("post_id"),
                reference=reference or None,
                product_name=product_name,
                brand=brand,
                category_name=category_name,
                detail_url=detail_url,
                image_url=image_url,
                image_alt=image_alt,
                page_number=page_number,
                source_page_url=source_page_url,
                searchable_tokens=build_searchable_tokens(reference, product_name, brand, category_name),
                match_type=match_type,
                match_confidence=match_confidence,
            )
        )
    return products


def extract_products_from_dom(page, source_page_url: str, page_number: int) -> list[RepuesteraProduct]:
    try:
        rows = page.locator(PRODUCT_CONTAINER_SELECTOR).evaluate_all(
            """
            (wrappers) => {
              const text = (node) => (node ? (node.innerText || node.textContent || '') : '').trim();
              const attr = (node, name) => (node ? (node.getAttribute(name) || '') : '').trim();
              const visibleWrapper = wrappers.find((el) => el.getClientRects().length > 0) || wrappers[0];
              if (!visibleWrapper) return [];
              return Array.from(visibleWrapper.querySelectorAll('.jet-listing-grid__item[data-post-id]'))
                .filter((el) => el.getClientRects().length > 0)
                .map((el) => {
                  const link = el.querySelector('a.jet-listing-dynamic-image__link');
                  const img = el.querySelector('img.jet-listing-dynamic-image__img');
                  return {
                    post_id: el.getAttribute('data-post-id') || '',
                    detail_url: link ? (link.href || attr(link, 'href')) : '',
                    image_url: img ? (img.currentSrc || img.src || attr(img, 'src')) : '',
                    image_alt: img ? (attr(img, 'alt') || text(img)) : '',
                    fields: Array.from(el.querySelectorAll('.jet-listing-dynamic-field__content')).map((node) => text(node)).filter(Boolean),
                    terms: Array.from(el.querySelectorAll('.jet-listing-dynamic-terms__link')).map((node) => text(node)).filter(Boolean),
                  };
                });
            }
            """
        )
    except Exception:
        rows = []
    products: list[RepuesteraProduct] = []
    for data in rows:
        detail_url = canonical_url(str(data.get("detail_url") or ""))
        if not detail_url:
            continue
        fields = [normalize_text(value) for value in data.get("fields", []) if normalize_text(value)]
        terms = [normalize_text(value) for value in data.get("terms", []) if normalize_text(value)]
        post_id = str(data.get("post_id") or "")
        image_url = str(data.get("image_url") or "") or None
        image_alt = str(data.get("image_alt") or "") or None
        reference = fields[0] if len(fields) >= 1 else None
        product_name = fields[1] if len(fields) >= 2 else (image_alt or reference or "")
        brand = fields[2] if len(fields) >= 3 else (terms[0] if len(terms) >= 1 else None)
        category_name = fields[3] if len(fields) >= 4 else (terms[1] if len(terms) >= 2 else None)
        match_type, match_confidence = infer_match(reference, product_name, brand, category_name)
        products.append(
            RepuesteraProduct(
                post_id=post_id,
                reference=reference or None,
                product_name=product_name,
                brand=brand,
                category_name=category_name,
                detail_url=detail_url,
                image_url=image_url,
                image_alt=image_alt,
                page_number=page_number,
                source_page_url=source_page_url,
                searchable_tokens=build_searchable_tokens(reference, product_name, brand, category_name),
                match_type=match_type,
                match_confidence=match_confidence,
            )
        )
    return products
def build_diff(current_products: list[RepuesteraProduct], previous_snapshot_path: Path | None) -> dict[str, Any]:
    if not previous_snapshot_path or not previous_snapshot_path.exists():
        return {
            "previous_snapshot": None,
            "added_detail_urls": [product.detail_url for product in current_products],
            "removed_detail_urls": [],
            "changed_products": [],
        }

    previous_payload = json.loads(previous_snapshot_path.read_text(encoding="utf-8"))
    previous_products = {
        record["detail_url"]: record
        for record in previous_payload.get("products", [])
        if record.get("detail_url")
    }
    current_map = {product.detail_url: product for product in current_products}

    added = [url for url in current_map if url not in previous_products]
    removed = [url for url in previous_products if url not in current_map]
    changed_products: list[dict[str, Any]] = []

    for url, product in current_map.items():
        old = previous_products.get(url)
        if not old:
            continue
        changes: dict[str, Any] = {}
        for field_name in ("reference", "product_name", "brand", "category_name"):
            old_value = old.get(field_name)
            new_value = getattr(product, field_name)
            if old_value != new_value:
                changes[field_name] = {"old": old_value, "new": new_value}
        if changes:
            changed_products.append({"detail_url": url, "changes": changes})

    return {
        "previous_snapshot": str(previous_snapshot_path),
        "added_detail_urls": added,
        "removed_detail_urls": removed,
        "changed_products": changed_products,
    }


def previous_snapshot_file(output_dir: Path, snapshot_date: str) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(
        path / "extracted.json"
        for path in output_dir.iterdir()
        if path.is_dir() and path.name < snapshot_date and (path / "extracted.json").exists()
    )
    return candidates[-1] if candidates else None


def write_csv(path: Path, products: list[RepuesteraProduct]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "post_id",
                "reference",
                "product_name",
                "brand",
                "category_name",
                "detail_url",
                "image_url",
                "page_number",
                "match_type",
                "match_confidence",
            ],
        )
        writer.writeheader()
        for product in products:
            writer.writerow(
                {
                    "post_id": product.post_id,
                    "reference": product.reference,
                    "product_name": product.product_name,
                    "brand": product.brand,
                    "category_name": product.category_name,
                    "detail_url": product.detail_url,
                    "image_url": product.image_url,
                    "page_number": product.page_number,
                    "match_type": product.match_type,
                    "match_confidence": product.match_confidence,
                }
            )


def write_summary(path: Path, payload: dict[str, Any], diff: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = payload["summary"]
    lines = [
        f"# Repuestera Snapshot Summary - {payload['snapshot_date']}",
        "",
        f"Categories extracted: {summary['carousel_categories_extracted']}",
        f"Products extracted: {summary['products_extracted']}",
        f"Pages scanned: {summary['pages_scanned']}",
        f"Pages detected: {summary['pages_detected']}",
        f"Products detected in site config: {summary['products_detected_total']}",
        f"Products with reference: {summary['products_with_reference']}",
        f"Products with brand: {summary['products_with_brand']}",
        f"Products with category: {summary['products_with_category']}",
        f"Added products vs previous snapshot: {len(diff['added_detail_urls'])}",
        f"Removed products vs previous snapshot: {len(diff['removed_detail_urls'])}",
        f"Changed products vs previous snapshot: {len(diff['changed_products'])}",
        "",
        "This snapshot is read-only and intended for supplier matching.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_catalog(max_pages: int | None = None, user_agent: str = DEFAULT_USER_AGENT) -> tuple[list[CatalogCategory], list[RepuesteraProduct], int, int, int]:
    first_page_html = fetch_html(REPUSTERA_ROOT_URL, user_agent=user_agent)
    categories = parse_category_carousel(first_page_html)
    products_detected_total, detected_page_count = parse_page_config(first_page_html)
    page_count = detected_page_count
    if max_pages is not None:
        page_count = min(page_count, max_pages)

    products: list[RepuesteraProduct] = []
    seen_urls: set[str] = set()
    pages_scanned = 0

    sync_playwright = get_playwright()
    browser_path = detect_browser_executable()
    headed = _env_flag("REPUESTERA_HEADED", False)
    slow_mo = int(os.environ.get("REPUESTERA_SLOW_MO", "40") or "40")
    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"headless": not headed, "slow_mo": slow_mo}
        if browser_path:
            launch_kwargs["executable_path"] = browser_path
        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1440, "height": 960}, user_agent=user_agent)
        page = context.new_page()
        previous_first_url = ""
        try:
            for page_number in range(1, page_count + 1):
                page_url = build_catalog_page_url(page_number)
                page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1200)
                close_registration_modal(page)
                wait_for_product_grid(page, previous_first_url)
                close_registration_modal(page)
                page_products = extract_products_from_dom(page, canonical_url(page.url), page_number)
                if not page_products:
                    break
                previous_first_url = page_products[0].detail_url
                pages_scanned += 1
                for product in page_products:
                    if product.detail_url not in seen_urls:
                        products.append(product)
                        seen_urls.add(product.detail_url)
        finally:
            context.close()
            browser.close()

    return categories, products, pages_scanned, detected_page_count, products_detected_total


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-date", default=str(date.today()))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--csv-output", type=Path, default=None)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--diff-output", type=Path, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    snapshot_dir = args.output_root / args.snapshot_date
    json_output = args.json_output or snapshot_dir / "extracted.json"
    csv_output = args.csv_output or snapshot_dir / "products.csv"
    summary_output = args.summary_output or snapshot_dir / "summary.md"
    diff_output = args.diff_output or snapshot_dir / "diff.json"

    categories, products, pages_scanned, pages_detected, products_detected_total = extract_catalog(
        max_pages=args.max_pages,
        user_agent=args.user_agent,
    )
    previous_snapshot = previous_snapshot_file(args.output_root, args.snapshot_date)
    diff = build_diff(products, previous_snapshot)

    payload = {
        "provider_id": "repuestera",
        "provider_name": "Repuestera",
        "snapshot_date": args.snapshot_date,
        "timezone": "America/Bogota",
        "catalog_root_url": REPUSTERA_ROOT_URL,
        "category_carousel": [asdict(category) for category in categories],
        "products": [asdict(product) for product in products],
        "summary": {
            "carousel_categories_extracted": len(categories),
            "products_extracted": len(products),
            "pages_scanned": pages_scanned,
            "pages_detected": pages_detected,
            "products_detected_total": products_detected_total,
            "products_with_reference": sum(1 for product in products if product.reference),
            "products_with_brand": sum(1 for product in products if product.brand),
            "products_with_category": sum(1 for product in products if product.category_name),
        },
    }

    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(csv_output, products)
    diff_output.write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_summary(summary_output, payload, diff)

    print(
        f"Extracted {len(products)} Repuestera product(s) across {pages_scanned} page(s). "
        f"Output: {json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


