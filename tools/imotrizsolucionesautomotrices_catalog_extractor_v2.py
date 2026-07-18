from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from playwright.sync_api import sync_playwright

PROVIDER_ID = "imotrizsolucionesautomotrices"
ROOT_URL = "https://www.imotriz.com/tienda/solucionesautomotrices"
CATALOG_URL = f"{ROOT_URL}/catalogo/page/results?search="
FALLBACK_URLS = (
    CATALOG_URL,
    f"{ROOT_URL}/catalogo",
    ROOT_URL + "/",
    ROOT_URL + "/home",
)

HEADLESS_ENV = f"{PROVIDER_ID.upper()}_HEADED"
WAIT_FOR_HUMAN_ENV = f"{PROVIDER_ID.upper()}_WAIT_FOR_HUMAN"
PERSISTENT_CONTEXT_ENV = f"{PROVIDER_ID.upper()}_PERSISTENT_CONTEXT"
USER_DATA_DIR_ENV = f"{PROVIDER_ID.upper()}_USER_DATA_DIR"
TIMEOUT_ENV = f"{PROVIDER_ID.upper()}_TIMEOUT_SECONDS"
DEBUG_ENV = f"{PROVIDER_ID.upper()}_DEBUG"

EXCLUDE_KEYWORDS = (
    "moto",
    "motoc",
    "camion",
    "camiones",
    "bus",
    "buses",
    "tracto",
    "industrial",
    "agricola",
    "npr",
    "heavy",
)

OUTPUT_COLUMNS = (
    "provider_id",
    "source_url",
    "title",
    "description",
    "brand",
    "sku",
    "reference",
    "price",
    "currency",
    "image_url",
    "category",
    "subcategory",
    "source_type",
)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-") or "catalog"


def _now_stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in (
            "title",
            "name",
            "productName",
            "description",
            "shortDescription",
            "descripcion",
            "marca",
            "brand",
            "sku",
            "reference",
            "url",
            "href",
        ):
            if key in value:
                text = _text(value.get(key))
                if text:
                    return text
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _text(item)
            if text:
                return text
    return ""


def _first_field(obj: Any, *paths: str) -> str:
    if not isinstance(obj, dict):
        return ""
    for path in paths:
        current: Any = obj
        ok = True
        for piece in path.split("."):
            if isinstance(current, dict) and piece in current:
                current = current[piece]
            else:
                ok = False
                break
        if ok:
            text = _text(current)
            if text:
                return text
    return ""


def _candidate_lists(payload: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("products", "items", "data", "resultProducts"):
                value = node.get(key)
                if isinstance(value, list) and value and all(isinstance(i, dict) for i in value):
                    found.append(value)
                elif isinstance(value, dict):
                    for nested_key in ("data", "items", "results"):
                        nested = value.get(nested_key)
                        if isinstance(nested, list) and nested and all(isinstance(i, dict) for i in nested):
                            found.append(nested)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload)
    # Keep only the lists that look like actual products.
    scored: list[tuple[int, list[dict[str, Any]]]] = []
    for items in found:
        score = 0
        for item in items[:15]:
            keys = {str(k).lower() for k in item.keys()}
            if keys & {"title", "name", "description", "productname", "sku", "reference", "price"}:
                score += 1
        scored.append((score, items))
    scored.sort(key=lambda pair: (len(pair[1]), pair[0]), reverse=True)
    return [items for _, items in scored]


def _clean_description(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _should_skip(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in EXCLUDE_KEYWORDS)


def _normalize_product(item: dict[str, Any], source_url: str) -> dict[str, Any] | None:
    title = _first_field(
        item,
        "title",
        "name",
        "productName",
        "product_name",
        "descripcion",
        "description",
        "summary",
    )
    description = _first_field(
        item,
        "description",
        "shortDescription",
        "excerpt",
        "body",
        "details",
        "content",
    )
    brand = _first_field(item, "brand", "marca", "manufacturer")
    sku = _first_field(item, "sku", "code", "reference", "partNumber", "part_number")
    reference = _first_field(item, "reference", "ref", "code", "partNumber")
    price = _first_field(item, "price", "salePrice", "regularPrice", "finalPrice", "amount")
    currency = _first_field(item, "currency", "currencyCode") or "COP"
    image_url = _first_field(item, "image", "imageUrl", "thumbnail", "image_url", "img")
    category = _first_field(item, "category", "categoryName", "group", "grupo")
    subcategory = _first_field(item, "subcategory", "subCategory", "subcategoryName")
    url = _first_field(item, "url", "href", "link", "productUrl", "product_url", "detailUrl")

    if not url:
        slug = _first_field(item, "slug", "seoUrl", "path")
        identifier = _first_field(item, "id", "productId", "product_id", "reference", "sku")
        if slug:
            url = f"{ROOT_URL}/{slug.lstrip('/')}"
        elif identifier:
            url = f"{ROOT_URL}/producto/{identifier}"

    if not title:
        title = _clean_description(description)

    if not title and not description:
        return None

    blob = " ".join(
        part
        for part in (
            title,
            description,
            brand,
            sku,
            reference,
            category,
            subcategory,
            url,
        )
        if part
    )
    if blob and _should_skip(blob):
        return None

    title = _clean_description(title)
    description = _clean_description(description)
    if not description and title:
        description = title

    record = {
        "provider_id": PROVIDER_ID,
        "source_url": url or source_url,
        "title": title,
        "description": description,
        "brand": brand,
        "sku": sku,
        "reference": reference,
        "price": price,
        "currency": currency,
        "image_url": image_url,
        "category": category,
        "subcategory": subcategory,
        "source_type": "embedded_runtime",
    }
    return record


def _dedupe_products(products: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for product in products:
        key = (
            _text(product.get("source_url")).lower(),
            _text(product.get("sku")).lower(),
            _text(product.get("title")).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(product)
    return deduped


def _build_card_like_record(item: dict[str, Any], source_url: str) -> dict[str, Any] | None:
    text_blob = " ".join(str(v) for v in item.values() if isinstance(v, (str, int, float)))
    if not text_blob.strip():
        return None
    if _should_skip(text_blob):
        return None
    title = _clean_description(_text(item.get("title")) or _text(item.get("name")) or text_blob)
    description = _clean_description(
        _text(item.get("description"))
        or _text(item.get("shortDescription"))
        or _text(item.get("body"))
        or title
    )
    url = _text(item.get("url")) or source_url
    if not title and not description:
        return None
    return {
        "provider_id": PROVIDER_ID,
        "source_url": url,
        "title": title,
        "description": description,
        "brand": _text(item.get("brand")) or _text(item.get("marca")),
        "sku": _text(item.get("sku")),
        "reference": _text(item.get("reference")),
        "price": _text(item.get("price")),
        "currency": _text(item.get("currency")) or "COP",
        "image_url": _text(item.get("image")) or _text(item.get("image_url")),
        "category": _text(item.get("category")) or _text(item.get("group")),
        "subcategory": _text(item.get("subcategory")),
        "source_type": "card_fallback",
    }


def _dismiss_popups(page) -> None:
    selectors = [
        "#cmplz-cookiebanner-1-optin",
        "#cmplz-cookiebanner-1 .cmplz-accept",
        ".cmplz-accept",
        ".cmplz-btn.cmplz-accept",
        "button:has-text('Aceptar')",
        "button:has-text('Entendido')",
        "button:has-text('Aceptar todo')",
        "button:has-text('Cerrar')",
        "button:has-text('No gracias')",
        "button:has-text('OK')",
        "button:has-text('No soy un robot')",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=1200)
                page.wait_for_timeout(700)
        except Exception:
            continue


def _wait_for_catalog_ready(page, timeout_seconds: int, wait_for_human: bool) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            ready = page.evaluate(
                """
                () => {
                    const hasBlob = !!window.searchProductsData;
                    const bodyText = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
                    const challenge = bodyText.includes('verifica') || bodyText.includes('validación') || bodyText.includes('un momento');
                    const productLinks = document.querySelectorAll('a[href*="/producto/"]').length;
                    return {hasBlob, challenge, productLinks};
                }
                """
            )
            if ready and ready.get("hasBlob"):
                return
            if wait_for_human and ready and ready.get("challenge"):
                page.wait_for_timeout(2500)
                continue
            if ready and ready.get("productLinks", 0) > 0:
                return
        except Exception:
            pass
        page.wait_for_timeout(1500)


def _extract_runtime_payload(page) -> dict[str, Any] | None:
    try:
        result = page.evaluate(
            """
            () => {
                const raw = window.searchProductsData || null;
                if (!raw) {
                    return { ok: false, reason: 'missing-searchProductsData' };
                }
                let parsed;
                try {
                    parsed = JSON.parse(atob(raw));
                } catch (error) {
                    return { ok: false, reason: `base64-parse:${error.message}` };
                }

                const roots = [
                    document.querySelector('#catalog-embed-vue-app'),
                    document.querySelector('#home-embed-vue-app'),
                    document.querySelector('#appView'),
                    document.body,
                ].filter(Boolean);

                const seen = new Set();
                const proxies = [];
                const add = (candidate, label) => {
                    if (!candidate) return;
                    try {
                        if (seen.has(candidate)) return;
                        seen.add(candidate);
                    } catch (error) {
                        return;
                    }
                    proxies.push({ candidate, label });
                };

                const collect = (node) => {
                    if (!node) return;
                    try { add(node.__vueParentComponent && node.__vueParentComponent.proxy, 'parent.proxy'); } catch (error) {}
                    try { add(node.__vueParentComponent && node.__vueParentComponent.ctx, 'parent.ctx'); } catch (error) {}
                    try { add(node.__vue_app__ && node.__vue_app__._instance && node.__vue_app__._instance.proxy, 'app.proxy'); } catch (error) {}
                    try { add(node.__vue_app__ && node.__vue_app__._instance && node.__vue_app__._instance.ctx, 'app.ctx'); } catch (error) {}
                };

                for (const root of roots) {
                    collect(root);
                    if (root && root.querySelectorAll) {
                        root.querySelectorAll('*').forEach(collect);
                    }
                }

                const targetNames = ['_', 'decrypt', 'loadProducts', 'parseProducts', 'decodeProducts'];
                const tryCall = (target, label) => {
                    if (!target) return null;
                    for (const name of targetNames) {
                        const fn = target[name];
                        if (typeof fn === 'function') {
                            try {
                                const value = fn.call(target, parsed);
                                return { source: `${label}.${name}`, value };
                            } catch (error) {
                                try {
                                    const value = fn(parsed);
                                    return { source: `${label}.${name}`, value };
                                } catch (error2) {}
                            }
                        }
                    }
                    for (const key of Object.keys(target)) {
                        const fn = target[key];
                        if (typeof fn !== 'function') continue;
                        const lower = String(key).toLowerCase();
                        if (key === '_' || lower.includes('decrypt') || lower.includes('loadproduct') || lower.includes('parse')) {
                            try {
                                const value = fn.call(target, parsed);
                                return { source: `${label}.${key}`, value };
                            } catch (error) {
                                try {
                                    const value = fn(parsed);
                                    return { source: `${label}.${key}`, value };
                                } catch (error2) {}
                            }
                        }
                    }
                    return null;
                };

                for (const { candidate, label } of proxies) {
                    const targets = [
                        candidate,
                        candidate.$,
                        candidate.$ && candidate.$.proxy,
                        candidate.$ && candidate.$.ctx,
                        candidate.$ && candidate.$.setupState,
                        candidate.$ && candidate.$.appContext && candidate.$.appContext.config && candidate.$.appContext.config.globalProperties,
                    ].filter(Boolean);
                    for (const target of targets) {
                        const out = tryCall(target, label);
                        if (out) {
                            return { ok: true, source: out.source, payload: out.value, proxyCount: proxies.length };
                        }
                    }
                }

                return {
                    ok: true,
                    source: 'parsed-only',
                    payload: parsed,
                    proxyCount: proxies.length,
                };
            }
            """
        )
        if result and result.get("ok"):
            return result
    except Exception as exc:
        return {"ok": False, "reason": f"runtime-extract:{exc}"}
    return None


def _extract_products_from_payload(payload: Any, source_url: str) -> list[dict[str, Any]]:
    if payload is None:
        return []
    candidates = _candidate_lists(payload)
    normalized: list[dict[str, Any]] = []
    if candidates:
        for item in candidates[0]:
            record = _normalize_product(item, source_url)
            if record:
                normalized.append(record)
    elif isinstance(payload, dict):
        for key in ("products", "resultProducts", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        record = _normalize_product(item, source_url)
                        if record:
                            normalized.append(record)
                if normalized:
                    break
            elif isinstance(value, dict):
                nested = value.get("data") or value.get("items") or value.get("results")
                if isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, dict):
                            record = _normalize_product(item, source_url)
                            if record:
                                normalized.append(record)
                    if normalized:
                        break

    if not normalized:
        return []
    return _dedupe_products(normalized)


def _extract_dom_fallback(page, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        cards = page.locator('a[href*="/producto/"], .product, .product-card, li')
        total = min(cards.count(), 200)
        for index in range(total):
            card = cards.nth(index)
            try:
                if not card.is_visible():
                    continue
                href = ""
                try:
                    href = card.get_attribute("href") or ""
                except Exception:
                    href = ""
                if href and not href.startswith("http"):
                    href = f"https://www.imotriz.com{href}"
                text = ""
                try:
                    text = card.inner_text(timeout=1000)
                except Exception:
                    text = ""
                if not text:
                    continue
                if _should_skip(text):
                    continue
                image_url = ""
                try:
                    img = card.locator("img").first
                    if img.count():
                        image_url = img.get_attribute("src") or img.get_attribute("data-src") or ""
                except Exception:
                    image_url = ""
                title = ""
                for line in [line.strip() for line in text.splitlines() if line.strip()]:
                    if len(line) >= 4 and len(line) <= 140 and not re.search(r"\b(usd|cop|iva|stock|env[oí]o)\b", line.lower()):
                        title = line
                        break
                if not title:
                    continue
                record = {
                    "provider_id": PROVIDER_ID,
                    "source_url": href or source_url,
                    "title": title,
                    "description": title,
                    "brand": "",
                    "sku": "",
                    "reference": "",
                    "price": "",
                    "currency": "COP",
                    "image_url": image_url,
                    "category": "",
                    "subcategory": "",
                    "source_type": "dom_fallback",
                }
                records.append(record)
            except Exception:
                continue
    except Exception:
        return []
    return _dedupe_products(records)


def _write_csv(path: Path, products: list[dict[str, Any]]) -> None:
    _ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for item in products:
            row = {column: item.get(column, "") for column in OUTPUT_COLUMNS}
            writer.writerow(row)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot_paths(snapshot_date: str) -> tuple[Path, Path]:
    base = Path("supplier_catalog") / "providers" / PROVIDER_ID / "snapshots" / snapshot_date
    return base, base / "products.csv"


def crawl_provider() -> dict[str, Any]:
    headed = _env_flag(HEADLESS_ENV, default=False)
    wait_for_human = _env_flag(WAIT_FOR_HUMAN_ENV, default=False)
    persistent_context = _env_flag(PERSISTENT_CONTEXT_ENV, default=False)
    user_data_dir = os.getenv(USER_DATA_DIR_ENV) or str(
        Path("local") / "browser_profiles" / PROVIDER_ID
    )
    timeout_seconds = _env_int(TIMEOUT_ENV, 1200)
    debug = _env_flag(DEBUG_ENV, default=False)

    snapshot_date = _now_stamp()
    snapshot_dir, csv_path = _snapshot_paths(snapshot_date)
    _ensure_dir(snapshot_dir)

    browser_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=TranslateUI",
    ]

    products: list[dict[str, Any]] = []
    notes: list[str] = []
    source_url_used = ""

    with sync_playwright() as p:
        if persistent_context:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=not headed,
                args=browser_args,
                viewport={"width": 1440, "height": 960},
                ignore_https_errors=True,
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser = p.chromium.launch(
                headless=not headed,
                args=browser_args,
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 960},
                ignore_https_errors=True,
            )
            page = context.new_page()

        try:
            for candidate in FALLBACK_URLS:
                source_url_used = candidate
                if debug:
                    print(json.dumps({"event": "goto", "url": candidate}, ensure_ascii=False))
                page.goto(candidate, wait_until="domcontentloaded", timeout=120000)
                try:
                    page.wait_for_load_state("networkidle", timeout=45000)
                except Exception:
                    pass
                _dismiss_popups(page)
                _wait_for_catalog_ready(page, timeout_seconds=min(timeout_seconds, 180), wait_for_human=wait_for_human)

                runtime = _extract_runtime_payload(page)
                if debug:
                    print(
                        json.dumps(
                            {
                                "event": "runtime_payload",
                                "ok": bool(runtime and runtime.get("ok")),
                                "source": runtime.get("source") if runtime else None,
                                "reason": runtime.get("reason") if runtime else None,
                                "proxyCount": runtime.get("proxyCount") if runtime else None,
                            },
                            ensure_ascii=False,
                        )
                    )
                if runtime and runtime.get("ok"):
                    extracted = _extract_products_from_payload(runtime.get("payload"), candidate)
                    if extracted:
                        products.extend(extracted)
                        notes.append(f"runtime:{candidate}:{len(extracted)}")
                        break

                fallback = _extract_dom_fallback(page, candidate)
                if fallback:
                    products.extend(fallback)
                    notes.append(f"dom:{candidate}:{len(fallback)}")
                    break

            products = _dedupe_products(products)

            payload = {
                "provider_id": PROVIDER_ID,
                "generated_at": dt.datetime.now().isoformat(),
                "source_url": source_url_used,
                "product_count": len(products),
                "notes": notes,
                "products": products,
                "stats": {
                    "runtime_products": sum(1 for p in products if p.get("source_type") == "embedded_runtime"),
                    "dom_products": sum(1 for p in products if p.get("source_type") == "dom_fallback"),
                },
            }
            _write_json(snapshot_dir / "extracted.json", payload)
            _write_csv(csv_path, products)
            _write_json(
                snapshot_dir / "progress.json",
                {
                    "provider_id": PROVIDER_ID,
                    "generated_at": dt.datetime.now().isoformat(),
                    "notes": notes,
                    "product_count": len(products),
                    "source_url": source_url_used,
                },
            )
            return {
                "provider_id": PROVIDER_ID,
                "snapshot_path": str(snapshot_dir / "extracted.json"),
            }
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                if not persistent_context:
                    browser.close()
            except Exception:
                pass


def main() -> int:
    result = crawl_provider()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
