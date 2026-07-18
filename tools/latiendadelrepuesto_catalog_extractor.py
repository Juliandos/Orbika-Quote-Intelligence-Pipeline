#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.seeded_catalog_support import (  # noqa: E402
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
    build_searchable_tokens,
    canonical_url,
    dedupe_records,
    latest_snapshot_json,
    load_json,
    provider_paths,
    same_host,
    write_snapshot_bundle,
)

PROVIDER_ID = "latiendadelrepuesto"
DISPLAY_NAME = "La Tienda del Repuesto"
HOME_URL = "https://latiendadelrepuesto.com/"
PORTAFOLIO_URL = "https://latiendadelrepuesto.com/portafolio/"

DISCOVERY_ENTRY_URLS = (HOME_URL, PORTAFOLIO_URL)
EXCLUDED_PATH_SEGMENTS = (
    "blog",
    "contacto",
    "quienes-somos",
    "puntos-de-venta",
    "transparencia",
    "portal-empleados",
    "politicas",
    "normatividad",
    "trabaja-con-nosotros",
)
GENERIC_HEADINGS = {
    "productos",
    "quienes somos",
    "enlaces de interes",
    "portafolio",
    "boletin",
    "cotiza aqui",
    "cotiza aqui tu repuesto",
    "inicio",
}
GENERIC_HEADING_MARKERS = (
    "repuestos originales y homologados",
    "encuentra para los vehículos",
    "encuentra para los vehiculos",
    "somos especialistas",
    "amplio portafolio",
    "lo mejor en bombilleria",
    "lo mejor en bombillería",
    "nuestro portafolio",
    "y mucho más",
    "y mucho mas",
    "repuestos para vehículos",
    "repuestos para vehiculos",
)
KNOWN_BRANDS = (
    "gti",
    "osram",
    "tecnocaucho",
    "acdelco",
    "valeo",
    "nes",
    "champion",
    "gmsgs",
    "willard",
    "3bbb",
    "taiho",
    "liftgate",
)
VEHICLE_TOKENS = (
    "chevrolet",
    "renault",
    "hyundai",
    "kia",
    "mazda",
    "suzuki",
    "hino",
    "isuzu",
    "toyota",
    "peugeot",
    "volkswagen",
    "audi",
    "fiat",
    "skoda",
    "nissan",
    "mitsubishi",
    "ford",
    "chery",
)


def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/latiendadelrepuesto_catalog_extractor.py`."
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


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", _clean(value)).casefold()


def _page_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path or "/"


def _is_catalog_url(url: str, host: str) -> bool:
    if not url.startswith("http"):
        return False
    if not same_host(url, host):
        return False
    path = _page_slug(url)
    if path in {"/", "/portafolio"}:
        return True
    if any(segment in path for segment in EXCLUDED_PATH_SEGMENTS):
        return False
    return path.count("/") == 1


def _derive_page_name(title: str, url: str) -> str:
    cleaned = _clean(title)
    if cleaned:
        base = cleaned.split(" - ", 1)[0].strip()
        if base:
            return base
    slug = _page_slug(url).strip("/")
    return _clean(slug.replace("-", " ")).title() or DISPLAY_NAME


def _close_popups(page) -> None:
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


def _discover_urls(page, host: str) -> list[str]:
    try:
        hrefs = page.locator("a[href]").evaluate_all(
            "els => els.map((el) => el.href || el.getAttribute('href') || '').filter(Boolean)"
        )
    except Exception:
        hrefs = []
    urls: list[str] = []
    seen: set[str] = set()
    for href in [*DISCOVERY_ENTRY_URLS, *hrefs]:
        normalized = canonical_url(href)
        if normalized in seen:
            continue
        if _is_catalog_url(normalized, host):
            urls.append(normalized)
            seen.add(normalized)
    return urls


def _extract_body_lines(page) -> list[str]:
    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body_text = ""
    return [line.strip() for line in body_text.splitlines() if line.strip()]


def _extract_intro_description(lines: list[str], page_name: str) -> str | None:
    normalized_page = _normalize(page_name)
    started = False
    for line in lines:
        normalized = _normalize(line)
        if not started:
            if normalized == normalized_page:
                started = True
            continue
        if normalized in GENERIC_HEADINGS:
            continue
        if normalized.startswith("inicio") and normalized != normalized_page:
            continue
        if normalized.startswith("cotiza aqui"):
            continue
        if len(line) < 25:
            continue
        return _clean(line)
    return None


def _should_skip_heading(text: str, page_name: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return True
    if normalized == _normalize(page_name):
        return True
    if normalized in GENERIC_HEADINGS:
        return True
    return any(marker in normalized for marker in GENERIC_HEADING_MARKERS)


def _infer_brand(text: str, block_text: str | None = None) -> str | None:
    haystack = f"{text} {block_text or ''}".casefold()
    for brand in KNOWN_BRANDS:
        if brand in haystack:
            return brand.upper() if brand.isalpha() else brand
    paren = re.search(r"\(([^)]{2,40})\)", text)
    if paren:
        return _clean(paren.group(1))
    return None


def _infer_match_type(text: str, description: str | None = None) -> tuple[str, str, bool]:
    haystack = f"{text} {description or ''}".casefold()
    if any(token in haystack for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def _slugify(value: str) -> str:
    slug = _normalize(value)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "item"


def _collect_section_candidates(page) -> list[dict[str, str]]:
    try:
        candidates = page.evaluate(
            """() => {
              const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };

              const gatherFollowingText = (element) => {
                const parts = [];
                let node = element.nextElementSibling;
                while (node) {
                  if (/^H[1-6]$/i.test(node.tagName)) {
                    break;
                  }
                  const text = (node.innerText || node.textContent || '').trim();
                  if (text) {
                    parts.push(text);
                  }
                  if (parts.join(' ').length > 500) {
                    break;
                  }
                  node = node.nextElementSibling;
                }
                return parts.join(' ').trim();
              };

              const items = [];
              for (const element of Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, img'))) {
                if (!isVisible(element)) {
                  continue;
                }
                if (element.tagName === 'IMG') {
                  const alt = (element.alt || '').trim();
                  const title = (element.title || '').trim();
                  const text = alt || title;
                  if (!text) {
                    continue;
                  }
                  const card = element.closest('a, article, section, li, div') || element.parentElement;
                  const blockText = (card?.innerText || card?.textContent || '').trim();
                  items.push({
                    kind: 'image',
                    text,
                    tag: 'IMG',
                    blockText,
                    href: card && card.href ? card.href : '',
                  });
                  continue;
                }
                const text = (element.innerText || element.textContent || '').trim();
                if (!text) {
                  continue;
                }
                const blockText = gatherFollowingText(element);
                const href = element.closest('a[href]')?.href || '';
                items.push({
                  kind: 'heading',
                  text,
                  tag: element.tagName,
                  blockText,
                  href,
                });
              }
              return items;
            }"""
        )
    except Exception:
        candidates = []
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in candidates or []:
        text = _clean(item.get("text"))
        if not text:
            continue
        key = _normalize(text)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "kind": _clean(item.get("kind")),
                "text": text,
                "tag": _clean(item.get("tag")),
                "block_text": _clean(item.get("blockText")),
                "href": _clean(item.get("href")),
            }
        )
    return results


def _build_product_record(*, page_url: str, page_name: str, item: dict[str, str]) -> ProductRecord | None:
    product_name = _clean(item.get("text"))
    if not product_name or _should_skip_heading(product_name, page_name):
        return None
    description = item.get("block_text") or None
    brand = _infer_brand(product_name, description)
    category_name = page_name
    subcategory_name = product_name
    match_type, confidence, manual = _infer_match_type(f"{product_name} {category_name}", description)
    section_slug = _slugify(product_name)
    detail_url = f"{page_url.rstrip('/')}?section={section_slug}"
    record = ProductRecord(
        item_type="product",
        provider_type="product_catalog",
        product_name=product_name,
        detail_url=detail_url,
        product_url=page_url,
        category_name=category_name,
        subcategory_name=subcategory_name,
        brand=brand,
        description=description,
        source_page_url=page_url,
        page_number=1,
        match_type=match_type,
        match_confidence=confidence,
        requires_manual_confirmation=manual,
        searchable_tokens=build_searchable_tokens(product_name, category_name, subcategory_name, brand, description),
    )
    return record


def _build_category_record(*, page_url: str, page_name: str, description: str | None, vehicle_scope: str | None = None) -> ProductRecord:
    return ProductRecord(
        item_type="category",
        provider_type="category_only",
        title=page_name,
        detail_url=page_url,
        category_name=page_name,
        description=description,
        vehicle_scope=vehicle_scope,
        source_page_url=page_url,
        page_number=1,
        match_type="category_only",
        match_confidence="medium",
        requires_manual_confirmation=True,
        searchable_tokens=build_searchable_tokens(page_name, description, vehicle_scope),
    )


def _extract_vehicle_scope(text: str) -> str | None:
    haystack = _normalize(text)
    if any(token in haystack for token in ("automóviles", "automoviles", "camionetas", "utilitarios", "semipesados", "autos")):
        return "Autos"
    return None


def run_extractor(snapshot_date: str | None = None) -> dict[str, Any]:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    snapshot_day = snapshot_date or date.today().isoformat()
    notes = [MANUAL_NOTE, "Extraction follows the public portafolio and category pages, capturing visible family/product titles from each page."]

    sync_playwright = get_playwright()
    browser_path = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip() or shutil.which("chromium-browser") or shutil.which("chromium")
    headless = not _env_flag(f"{PROVIDER_ID.upper()}_HEADED", default=False)
    discovered_urls: list[str] = []
    page_evidence: list[dict[str, Any]] = []
    records: list[ProductRecord] = []
    category_pages_with_products = 0

    with sync_playwright() as p:
        browser_kwargs: dict[str, Any] = {"headless": headless}
        if browser_path:
            browser_kwargs["executable_path"] = browser_path
        browser = p.chromium.launch(**browser_kwargs)
        context = browser.new_context(viewport={"width": 1600, "height": 2200}, locale="es-CO")
        page = context.new_page()
        try:
            visited_for_discovery: set[str] = set()
            for entry_url in DISCOVERY_ENTRY_URLS:
                page.goto(entry_url, wait_until="networkidle", timeout=120000)
                _close_popups(page)
                host = urlparse(entry_url).netloc.lower()
                for candidate in _discover_urls(page, host):
                    if candidate not in visited_for_discovery:
                        visited_for_discovery.add(candidate)
                        discovered_urls.append(candidate)

            catalog_urls = [url for url in discovered_urls if _is_catalog_url(url, urlparse(HOME_URL).netloc.lower())]
            for page_url in catalog_urls:
                if page_url.rstrip("/") in {HOME_URL.rstrip("/"), PORTAFOLIO_URL.rstrip("/")}: 
                    continue
                page.goto(page_url, wait_until="networkidle", timeout=120000)
                _close_popups(page)
                page.wait_for_timeout(500)
                page_title = page.title()
                page_name = _derive_page_name(page_title, page_url)
                lines = _extract_body_lines(page)
                intro_description = _extract_intro_description(lines, page_name)
                vehicle_scope = _extract_vehicle_scope(" ".join(lines))
                candidates = _collect_section_candidates(page)
                product_records: list[ProductRecord] = []
                for item in candidates:
                    if item.get("kind") not in {"heading", "image"}:
                        continue
                    record = _build_product_record(page_url=page_url, page_name=page_name, item=item)
                    if record is None:
                        continue
                    product_records.append(record)
                product_records = dedupe_records(product_records, ())
                if product_records:
                    category_pages_with_products += 1
                    records.extend(product_records)
                elif page_name and page_name.lower() not in {"inicio", "portafolio"}:
                    records.append(_build_category_record(page_url=page_url, page_name=page_name, description=intro_description, vehicle_scope=vehicle_scope))
                page_evidence.append(
                    {
                        "page_url": page_url,
                        "page_title": page_title,
                        "page_name": page_name,
                        "product_count": len(product_records),
                        "product_names": [record.product_name for record in product_records],
                        "intro_description": intro_description,
                        "vehicle_scope": vehicle_scope,
                    }
                )
        finally:
            try:
                page.close()
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

    deduped = dedupe_records(records, ())
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=deduped,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    extracted_path = write_snapshot_bundle(output_root=output_root, snapshot_date=snapshot_day, payload=payload, products=deduped)
    snapshot_dir = extracted_path.parent
    (snapshot_dir / "page_evidence.json").write_text(json.dumps(page_evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "completed" if deduped else "failed",
        "provider_id": PROVIDER_ID,
        "snapshot_path": str(extracted_path),
        "snapshot_dir": str(snapshot_dir),
        "discovered_pages": len([url for url in discovered_urls if _is_catalog_url(url, urlparse(HOME_URL).netloc.lower())]),
        "records": len(deduped),
        "category_pages_with_products": category_pages_with_products,
        "page_evidence": len(page_evidence),
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

