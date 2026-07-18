#!/usr/bin/env python3
from __future__ import annotations

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium-browser")
        page = browser.new_page(viewport={"width": 1600, "height": 2200}, locale="es-CO")
        url = "https://latiendadelrepuesto.com/colision/"
        page.goto(url, wait_until="networkidle", timeout=120000)
        print("TITLE", page.title())
        print("H1", page.locator("h1").all_inner_texts())
        print("HEADINGS", page.locator("h2, h3, h4, h5").all_inner_texts())
        print("LINKS", page.locator("a[href]").evaluate_all("els => els.slice(0, 80).map(e => ({text:(e.innerText||e.textContent||'').trim(), href:e.href}))"))
        print("BODY", page.locator("body").inner_text()[:3500])
        browser.close()


if __name__ == "__main__":
    main()

