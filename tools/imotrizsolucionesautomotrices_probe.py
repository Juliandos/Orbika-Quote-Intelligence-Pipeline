from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT_URL = "https://www.imotriz.com/tienda/solucionesautomotrices/catalogo"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=30)
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        requests: list[str] = []
        page.on("request", lambda req: requests.append(req.url))

        page.goto(ROOT_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(args.wait_seconds * 1000)

        html = page.content()
        matches = sorted(
            set(
                re.findall(
                    r"https?://[^\"'\\s<>]+|/[^\"'\\s<>]+",
                    html,
                )
            )
        )

        out = {
            "title": page.title(),
            "url": page.url,
            "requests": requests[-200:],
            "matches": [m for m in matches if any(k in m.lower() for k in ("catalog", "product", "search", "api", "graphql", "solucionesautomotrices"))],
            "scripts": [
                node
                for node in page.locator("script").evaluate_all(
                    """els => els.map((el, i) => ({
                        index: i,
                        src: el.src || null,
                        type: el.type || null,
                        text: (el.textContent || "").slice(0, 800)
                    }))"""
                )
            ],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
