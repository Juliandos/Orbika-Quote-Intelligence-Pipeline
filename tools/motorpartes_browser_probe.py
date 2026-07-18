#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from urllib.parse import urlparse

CATEGORY_URLS = [
    "https://www.motorpartes.co/categoria-producto/version-solas/",
    "https://www.motorpartes.co/categoria-producto/culata-completa/",
    "https://www.motorpartes.co/categoria-producto/ciguenales/",
    "https://www.motorpartes.co/categoria-producto/bielas-de-motor/",
    "https://www.motorpartes.co/categoria-producto/ejes-de-leva/",
    "https://www.motorpartes.co/categoria-producto/valvulas/",
    "https://www.motorpartes.co/categoria-producto/motor-completo/",
    "https://www.motorpartes.co/categoria-producto/motores-7-8/",
    "https://www.motorpartes.co/categoria-producto/bloques-de-motor/",
    "https://www.motorpartes.co/categoria-producto/descuentos/",
]
PRODUCT_CONTAINER = "#main-content > div > div > div.et_pb_section.et_pb_section_2_tb_body.et_pb_with_background.et_section_regular > div > div > div > div > div.dipl_woo_products_layout.layout1"
PAGINATION_SELECTOR = "#main-content > div > div > div.et_pb_section.et_pb_section_2_tb_body.et_pb_with_background.et_section_regular > div > div > div > div > div.dipl_woo_products_pagination_wrapper > ul"
COOKIE_ACCEPT_SELECTOR = "#cmplz-cookiebanner-1-optin"
CHAT_SELECTORS = [
    "#qlwapp",
    ".qlwapp",
    ".joinchat",
    "[class*='chat']",
    "[class*='whatsapp']",
]



def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/motorpartes_browser_probe.py`"
        ) from exc
    return sync_playwright

def detect_browser_executable() -> str | None:
    for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def accept_cookies(page) -> None:
    try:
        button = page.locator(COOKIE_ACCEPT_SELECTOR).first
        if button.count() > 0 and button.is_visible():
            try:
                button.click(timeout=2500)
            except Exception:
                page.evaluate(
                    """
                    (selector) => {
                      const node = document.querySelector(selector);
                      if (node) node.click();
                    }
                    """,
                    COOKIE_ACCEPT_SELECTOR,
                )
            page.wait_for_timeout(1200)
    except Exception:
        pass


def hide_chat_widgets(page) -> None:
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
            CHAT_SELECTORS,
        )
    except Exception:
        pass


def smooth_scroll(page, passes: int, pause_ms: int) -> None:
    for _ in range(max(passes, 1)):
        accept_cookies(page)
        hide_chat_widgets(page)
        try:
            page.locator(PRODUCT_CONTAINER).scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass
        try:
            page.mouse.wheel(0, 2200)
        except Exception:
            pass
        page.wait_for_timeout(pause_ms)


def current_page_number(page) -> int:
    try:
        active = page.evaluate(
            f"""
            () => {{
              const root = document.querySelector({PAGINATION_SELECTOR!r});
              if (!root) return '';
              const current = root.querySelector('.current, .active, .page-numbers.current, li .current');
              if (!current) return '';
              return (current.textContent || '').trim();
            }}
            """
        )
        if isinstance(active, str) and active.isdigit():
            return int(active)
    except Exception:
        pass
    parsed = urlparse(page.url)
    match = re.search(r"/page/(\d+)/?$", parsed.path)
    return int(match.group(1)) if match else 1


def discover_numeric_pages(page) -> list[int]:
    try:
        values = page.evaluate(
            f"""
            () => Array.from(document.querySelectorAll({PAGINATION_SELECTOR!r} + ' a, ' + {PAGINATION_SELECTOR!r} + ' span'))
              .map((node) => (node.textContent || '').trim())
              .filter((text) => /^\\d+$/.test(text))
            """
        )
    except Exception:
        values = []
    pages = sorted({int(value) for value in values if isinstance(value, str) and value.isdigit()})
    return [page_number for page_number in pages if page_number > 0]


def go_to_numeric_page(page, page_number: int) -> bool:
    accept_cookies(page)
    hide_chat_widgets(page)
    current = current_page_number(page)
    if current == page_number:
        return True
    escaped = str(page_number)
    selectors = [
        f"{PAGINATION_SELECTOR} a[aria-label='{escaped}']",
        f"{PAGINATION_SELECTOR} a:text-is('{escaped}')",
        f"{PAGINATION_SELECTOR} .page-numbers:text-is('{escaped}')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.scroll_into_view_if_needed(timeout=4000)
            accept_cookies(page)
            try:
                locator.click(timeout=4000)
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
            page.wait_for_function(
                """
                ({ rootSelector, expected }) => {
                  const root = document.querySelector(rootSelector);
                  if (!root) return false;
                  const current = root.querySelector('.current, .active, .page-numbers.current, li .current');
                  if (!current) return false;
                  return (current.textContent || '').trim() === String(expected);
                }
                """,
                arg={"rootSelector": PAGINATION_SELECTOR, "expected": page_number},
                timeout=12000,
            )
            page.wait_for_timeout(1200)
            return current_page_number(page) == page_number
        except Exception:
            accept_cookies(page)
            continue
    return current_page_number(page) == page_number


def go_to_next_page(page) -> bool:
    accept_cookies(page)
    hide_chat_widgets(page)
    selectors = [
        f"{PAGINATION_SELECTOR} a.next",
        f"{PAGINATION_SELECTOR} a.page-numbers.next",
        f"{PAGINATION_SELECTOR} a[rel='next']",
        f"{PAGINATION_SELECTOR} a[aria-label='Next page']",
        f"{PAGINATION_SELECTOR} li:last-child a",
    ]
    current = current_page_number(page)
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.scroll_into_view_if_needed(timeout=4000)
            accept_cookies(page)
            try:
                locator.click(timeout=4000)
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
            page.wait_for_function(
                """
                ({ rootSelector, currentValue }) => {
                  const root = document.querySelector(rootSelector);
                  if (!root) return false;
                  const current = root.querySelector('.current, .active, .page-numbers.current, li .current');
                  if (!current) return false;
                  const text = (current.textContent || '').trim();
                  return /^\\d+$/.test(text) && Number(text) > Number(currentValue);
                }
                """,
                arg={"rootSelector": PAGINATION_SELECTOR, "currentValue": current},
                timeout=12000,
            )
            page.wait_for_timeout(1200)
            return current_page_number(page) > current
        except Exception:
            accept_cookies(page)
            continue
    return False


def settle_category_view(page, scroll_passes: int, pause_ms: int) -> None:
    accept_cookies(page)
    hide_chat_widgets(page)
    smooth_scroll(page, scroll_passes, pause_ms)


def collect_product_links_on_page(page) -> list[str]:
    try:
        hrefs = page.evaluate(
            """
            (selector) => {
              const root = document.querySelector(selector) || document;
              return Array.from(root.querySelectorAll('a[href]'))
                .map((node) => node.href || node.getAttribute('href') || '')
                .filter(Boolean);
            }
            """,
            PRODUCT_CONTAINER,
        )
    except Exception:
        hrefs = []
    links: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        if '/producto/' not in href.lower():
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append(href)
    return links
def auto_walk_category(page, max_pages: int, scroll_passes: int, pause_ms: int) -> None:
    settle_category_view(page, scroll_passes, pause_ms)
    visited_pages = {current_page_number(page)}
    while True:
        current = current_page_number(page)
        if max_pages > 0 and current >= max_pages:
            break
        discovered_pages = [n for n in discover_numeric_pages(page) if n not in visited_pages and n > current]
        moved = False
        for page_number in discovered_pages:
            if max_pages > 0 and page_number > max_pages:
                break
            if not go_to_numeric_page(page, page_number):
                continue
            visited_pages.add(current_page_number(page))
            settle_category_view(page, scroll_passes, pause_ms)
            moved = True
            break
        if moved:
            continue
        if go_to_next_page(page):
            visited_pages.add(current_page_number(page))
            settle_category_view(page, scroll_passes, pause_ms)
            continue
        break


def walk_urls(page, urls: list[str], max_pages: int, scroll_passes: int, pause_ms: int) -> None:
    for url in urls:
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(1800)
        settle_category_view(page, scroll_passes, pause_ms)
        auto_walk_category(page, max_pages, scroll_passes, pause_ms)


def main() -> int:
    parser = argparse.ArgumentParser(description="Abrir Motorpartes en navegador visible para inspeccion guiada")
    parser.add_argument("url", nargs="?", default="")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--scroll-passes", type=int, default=3)
    parser.add_argument("--pause-ms", type=int, default=1800)
    parser.add_argument("--manual-only", action="store_true")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Instala Playwright con: uv run --with playwright python tools/motorpartes_browser_probe.py"
        ) from exc

    urls = [args.url] if args.url else CATEGORY_URLS
    browser_path = detect_browser_executable()
    with sync_playwright() as playwright:
        launch_kwargs = {"headless": False, "slow_mo": 80}
        if browser_path:
            launch_kwargs["executable_path"] = browser_path
        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        page = context.new_page()
        if args.manual_only:
            target = urls[0]
            page.goto(target, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(1800)
            settle_category_view(page, args.scroll_passes, args.pause_ms)
        else:
            walk_urls(page, urls, args.max_pages, args.scroll_passes, args.pause_ms)
        page.wait_for_timeout(args.timeout_seconds * 1000)
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

