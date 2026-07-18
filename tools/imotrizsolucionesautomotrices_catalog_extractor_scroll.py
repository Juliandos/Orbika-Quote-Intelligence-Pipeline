from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from tools.seeded_catalog_support import (  # noqa: E402
    AUTOS_ONLY_NOTE,
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
    build_searchable_tokens,
    dedupe_records,
    latest_snapshot_json,
    load_json,
    provider_paths,
    write_snapshot_bundle,
)

PROVIDER_ID = "imotrizsolucionesautomotrices"
DISPLAY_NAME = "Imotriz Soluciones Automotrices"
ROOT_URL = "https://www.imotriz.com/tienda/solucionesautomotrices"
CATALOG_URL = f"{ROOT_URL}/catalogo/page/results?search="

HEADLESS_ENV = f"{PROVIDER_ID.upper()}_HEADED"
WAIT_FOR_HUMAN_ENV = f"{PROVIDER_ID.upper()}_WAIT_FOR_HUMAN"
PERSISTENT_CONTEXT_ENV = f"{PROVIDER_ID.upper()}_PERSISTENT_CONTEXT"
USER_DATA_DIR_ENV = f"{PROVIDER_ID.upper()}_USER_DATA_DIR"
SCROLL_PAUSE_MS_ENV = f"{PROVIDER_ID.upper()}_SCROLL_PAUSE_MS"
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

CARD_NOISE = (
    "read more",
    "ver mÃ¡s",
    "ver mas",
    "agregar",
    "add to cart",
    "cotizar",
    "confirmar",
    "vehÃ­culos compatibles",
    "vehiculos compatibles",
    "costo de envÃ­o",
    "costo de envio",
    "entrega:",
    "impuesto incluido",
)

CHALLENGE_MARKERS = (
    "verifica",
    "verification",
    "verify",
    "captcha",
    "un momento",
    "momento",
    "human",
    "robot",
    "solicitud",
    "waiting",
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


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _should_skip(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in EXCLUDE_KEYWORDS)


def _dismiss_popups(page, skip_if_challenge: bool = False) -> None:
    if skip_if_challenge and _page_has_human_verification(page):
        return
    selectors = (
        "button:has-text('Aceptar')",
        "button:has-text('Acepto')",
        "button:has-text('Entendido')",
        "button:has-text('Cerrar')",
        "button:has-text('Close')",
        "button:has-text('Denegar')",
        "button:has-text('Deny')",
        "[aria-label*='close' i]",
        "[aria-label*='cerrar' i]",
        "[id*='cookie' i] button",
        "[class*='cookie' i] button",
        "[class*='popup' i] button",
        "[class*='modal' i] button",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=500):
                locator.click(timeout=1200, force=True)
                page.wait_for_timeout(250)
        except Exception:
            continue


def _page_has_human_verification(page) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body_text = ""
    lowered = (body_text or "").lower()
    return any(token in lowered for token in CHALLENGE_MARKERS)


def _wait_for_manual_verification(page, timeout_seconds: int, notes: list[str]) -> bool:
    deadline = time.time() + timeout_seconds
    notes.append("Se detectÃ³ validaciÃ³n humana; espera a resolverla sin cambiar de pÃ¡gina.")
    while time.time() < deadline:
        if not _page_has_human_verification(page):
            notes.append("La validaciÃ³n humana desapareciÃ³ y la extracciÃ³n siguiÃ³.")
            return True
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.wait_for_timeout(1000)
        except Exception:
            break
    notes.append("Timeout esperando validaciÃ³n humana; se siguiÃ³ con lo recuperable.")
    return False


def _extract_rendered_card_payloads(page) -> list[dict[str, str]]:
    try:
        payloads = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]')).map((a, index) => {
                const card = a.closest('article, li, .product, .products .product, .card, .item, .grid-item, .catalog-item, .product-card, .woocommerce-loop-product__link, div') || a;
                const image = card ? card.querySelector('img') : null;
                return {
                    href: a.href || '',
                    text: (card?.innerText || a.innerText || a.textContent || '').trim(),
                    title: (a.getAttribute('title') || '').trim(),
                    aria: (a.getAttribute('aria-label') || '').trim(),
                    image: image ? (image.currentSrc || image.src || '') : '',
                    index
                };
            })"""
        )
    except Exception:
        return []

    results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for payload in payloads or []:
        href = str(payload.get("href") or "")
        text = str(payload.get("text") or "")
        title = str(payload.get("title") or "")
        aria = str(payload.get("aria") or "")
        image = str(payload.get("image") or "")
        if not href:
            continue
        if image == "" and len(text) < 12:
            continue
        key = (href, text[:80])
        if key in seen:
            continue
        seen.add(key)
        results.append({"href": href, "text": text, "title": title, "aria": aria, "image": image})
    return results


def _infer_match_type(title: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, description, reference])).lower()
    if any(token in allowed_text for token in ("chevrolet", "mazda", "renault", "kia", "hyundai", "nissan", "toyota", "ford", "volkswagen")):
        return "vehicle_compatible", "medium", True
    if reference:
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def _build_card_record(payload: dict[str, str], source_page_url: str) -> ProductRecord | None:
    href = payload.get("href") or ""
    if not href.startswith("http"):
        return None
    text_lines = []
    for raw in (payload.get("text") or "").splitlines():
        line = _clean(raw)
        if not line:
            continue
        if any(noise in line.lower() for noise in CARD_NOISE):
            continue
        if len(line) < 3:
            continue
        text_lines.append(line)
    if not text_lines:
        text_lines = [_clean(payload.get("title") or ""), _clean(payload.get("aria") or "")]
        text_lines = [line for line in text_lines if line]
    if not text_lines:
        return None

    title = text_lines[0]
    description = " ".join(text_lines[1:4]).strip() if len(text_lines) > 1 else title
    blob = f"{title} {description} {href}"
    if _should_skip(blob):
        return None

    reference_match = re.search(
        r"\b(?:AT-\d+[A-Z]?|PF:\([^)]+\)|PF:\s*[A-Za-z0-9\-\/]+|[A-Z]{2,}\d{2,}[A-Z0-9\-]*)\b",
        blob,
        re.IGNORECASE,
    )
    reference = reference_match.group(0).strip() if reference_match else None
    match_type, match_confidence, requires_manual_confirmation = _infer_match_type(title, description, reference)

    return ProductRecord(
        item_type="product",
        provider_type=match_type,
        title=title,
        product_name=title,
        detail_url=href,
        product_url=href,
        category_name=None,
        subcategory_name=None,
        brand=None,
        reference=reference,
        sku=reference,
        supplier_item_code=None,
        description=description or None,
        vehicle_scope="autos",
        image_url=payload.get("image") or None,
        source_page_url=source_page_url,
        page_number=None,
        match_type=match_type,
        match_confidence=match_confidence,
        requires_manual_confirmation=requires_manual_confirmation,
        searchable_tokens=build_searchable_tokens(title, description, reference),
    )


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


def _extract_runtime_payload(page) -> dict[str, Any] | None:
    try:
        result = page.evaluate(
            """
            () => {
                const raw = window.searchProductsData || null;
                if (!raw) return { ok: false, reason: 'missing-searchProductsData' };
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

                return { ok: true, source: 'parsed-only', payload: parsed, proxyCount: proxies.length };
            }
            """
        )
        if result and result.get("ok"):
            return result
    except Exception as exc:
        return {"ok": False, "reason": f"runtime-extract:{exc}"}
    return None


def _extract_products_from_payload(payload: Any, source_url: str) -> list[ProductRecord]:
    records: list[ProductRecord] = []
    if payload is None:
        return records
    for items in _candidate_lists(payload):
        for item in items:
            title = _clean(_first_field(item, "title", "name", "productName", "product_name", "description", "summary"))
            description = _clean(_first_field(item, "description", "shortDescription", "excerpt", "body", "details", "content"))
            brand = _clean(_first_field(item, "brand", "marca", "manufacturer"))
            sku = _clean(_first_field(item, "sku", "code", "reference", "partNumber", "part_number"))
            image_url = _clean(_first_field(item, "image", "imageUrl", "thumbnail", "image_url", "img"))
            url = _clean(_first_field(item, "url", "href", "link", "productUrl", "product_url", "detailUrl"))
            if not url:
                slug = _clean(_first_field(item, "slug", "seoUrl", "path"))
                identifier = _clean(_first_field(item, "id", "productId", "product_id", "reference", "sku"))
                if slug:
                    url = f"{ROOT_URL}/{slug.lstrip('/')}"
                elif identifier:
                    url = f"{ROOT_URL}/producto/{identifier}"
            reference = _clean(_first_field(item, "reference", "ref", "code", "partNumber"))
            blob = " ".join(part for part in (title, description, brand, sku, reference, url) if part)
            if not title and description:
                title = description
            if not title or _should_skip(blob):
                continue
            if not description:
                description = title
            record = ProductRecord(
                item_type="product",
                provider_type="vehicle_compatible" if (brand or reference) else "category_only",
                title=title,
                product_name=title,
                detail_url=url or source_url,
                product_url=url or source_url,
                category_name=_clean(_first_field(item, "category", "categoryName", "group", "grupo")) or None,
                subcategory_name=_clean(_first_field(item, "subcategory", "subCategory", "subcategoryName")) or None,
                brand=brand or None,
                reference=reference or sku or None,
                sku=sku or reference or None,
                supplier_item_code=None,
                description=description or None,
                vehicle_scope="autos",
                image_url=image_url or None,
                source_page_url=source_url,
                page_number=None,
                match_type="vehicle_compatible" if (brand or reference) else "category_only",
                match_confidence="medium",
                requires_manual_confirmation=True,
                searchable_tokens=build_searchable_tokens(title, description, reference or sku),
            )
            records.append(record)
        if records:
            break
    return records


def _extract_dom_fallback(page, source_url: str) -> list[ProductRecord]:
    records: list[ProductRecord] = []
    try:
        cards = _extract_rendered_card_payloads(page)
    except Exception:
        return []
    for payload in cards:
        record = _build_card_record(payload, source_url)
        if record:
            records.append(record)
    return records


def _scroll_until_inventory_stops(
    page,
    wait_for_human: bool,
    notes: list[str],
    timeout_seconds: int,
    pause_ms: int,
    seen_cards: list[dict[str, str]],
) -> int:
    deadline = time.time() + timeout_seconds
    previous_count = len(seen_cards)
    stable_rounds = 0
    resume_rounds = 0
    rounds = 0
    while time.time() < deadline and rounds < 600:
        rounds += 1
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.mouse.wheel(0, 2600)
        except Exception:
            break
        try:
            page.wait_for_timeout(pause_ms)
        except Exception:
            break
        if wait_for_human and _page_has_human_verification(page):
            notes.append("ValidaciÃ³n humana detectada durante el scroll. Esperando sin salir del catÃ¡logo.")
            _wait_for_manual_verification(page, timeout_seconds, notes)
            stable_rounds = 0
            previous_count = len(seen_cards)
            resume_rounds = 6
            continue
        _dismiss_popups(page, skip_if_challenge=True)
        try:
            current_cards = _extract_rendered_card_payloads(page)
            existing = {(card.get("href", ""), card.get("text", "")[:120]) for card in seen_cards}
            for card in current_cards:
                key = (card.get("href", ""), card.get("text", "")[:120])
                if key in existing:
                    continue
                existing.add(key)
                seen_cards.append(card)
            current_count = len(seen_cards)
        except Exception:
            current_count = previous_count
        if resume_rounds > 0:
            resume_rounds -= 1
            stable_rounds = 0
        elif current_count <= previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_count = current_count
        if stable_rounds >= 10:
            break
    return rounds

def crawl_provider() -> dict[str, Any]:
    headed = _env_flag(HEADLESS_ENV, default=False)
    wait_for_human = _env_flag(WAIT_FOR_HUMAN_ENV, default=False)
    persistent_context = _env_flag(PERSISTENT_CONTEXT_ENV, default=False)
    user_data_dir = os.getenv(USER_DATA_DIR_ENV) or str(Path("local") / "browser_profiles" / PROVIDER_ID)
    timeout_seconds = _env_int(TIMEOUT_ENV, 1200)
    scroll_pause_ms = _env_int(SCROLL_PAUSE_MS_ENV, 1100)
    debug = _env_flag(DEBUG_ENV, default=False)

    snapshot_date = _now_stamp()
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    snapshot_dir = output_root / "snapshots" / snapshot_date
    _ensure_dir(snapshot_dir)

    browser_args = ["--disable-blink-features=AutomationControlled", "--disable-features=TranslateUI"]
    notes = [AUTOS_ONLY_NOTE, "Extractor browser-assisted: una sola ventana, una sola pÃ¡gina de catÃ¡logo y scroll hasta que el inventario deje de crecer."]
    products: list[ProductRecord] = []
    seen_cards: list[dict[str, str]] = []
    source_url = CATALOG_URL

    with sync_playwright() as p:
        if persistent_context:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=not headed,
                args=browser_args,
                viewport={"width": 1440, "height": 960},
                ignore_https_errors=True,
            )
            browser = None
        else:
            browser = p.chromium.launch(headless=not headed, args=browser_args)
            context = browser.new_context(viewport={"width": 1440, "height": 960}, ignore_https_errors=True)

        page = context.new_page()
        page.set_default_timeout(15000)

        try:
            if debug:
                print(json.dumps({"event": "goto", "url": source_url}, ensure_ascii=False))
            page.goto(source_url, wait_until="domcontentloaded", timeout=120000)
            try:
                page.wait_for_load_state("networkidle", timeout=45000)
            except Exception:
                pass
            _wait_for_catalog_ready(page, timeout_seconds=min(timeout_seconds, 180), wait_for_human=wait_for_human)
            if wait_for_human and _page_has_human_verification(page):
                notes.append('Validación humana detectada al abrir el catálogo. Esperando sin cerrarla.')
                _wait_for_manual_verification(page, timeout_seconds, notes)
            _dismiss_popups(page, skip_if_challenge=True)
            scroll_rounds = _scroll_until_inventory_stops(
                page,
                wait_for_human=wait_for_human,
                notes=notes,
                timeout_seconds=min(timeout_seconds, 600),
                pause_ms=scroll_pause_ms,
                seen_cards=seen_cards,
            )
            if debug:
                print(json.dumps({"event": "scroll_rounds", "rounds": scroll_rounds}, ensure_ascii=False))

            runtime = _extract_runtime_payload(page)
            if debug:
                print(json.dumps({"event": "runtime_payload", "ok": bool(runtime and runtime.get("ok")), "source": runtime.get("source") if runtime else None, "reason": runtime.get("reason") if runtime else None, "proxyCount": runtime.get("proxyCount") if runtime else None}, ensure_ascii=False))

            products = []
            if runtime and runtime.get("ok"):
                products.extend(_extract_products_from_payload(runtime.get("payload"), source_url))
            if not products:
                products.extend(_extract_dom_fallback(page, source_url))
            if seen_cards:
                for card in seen_cards:
                    record = _build_card_record(card, source_url)
                    if record:
                        products.append(record)
            products = dedupe_records(products, EXCLUDE_KEYWORDS)
            notes.append(f"Catalog scroll rounds: {scroll_rounds}")
            notes.append(f"Records after dedupe: {len(products)}")
            notes.append(MANUAL_NOTE)

            payload = build_payload(
                provider_id=PROVIDER_ID,
                provider_name=DISPLAY_NAME,
                metadata={"website": ROOT_URL, "catalog_root_url": ROOT_URL},
                products=products,
                notes=notes,
                snapshot_date=snapshot_date,
            )
            payload["catalog_coverage"] = {
                "catalog_url": source_url,
                "scroll_rounds": scroll_rounds,
                "headless": not headed,
                "wait_for_human": wait_for_human,
                "runtime_products": sum(1 for p in products if p.source_page_url == source_url),
                "total_products": len(products),
            }
            final_path = write_snapshot_bundle(output_root=output_root, snapshot_date=snapshot_date, payload=payload, products=products)
            _ensure_dir(snapshot_dir)
            (snapshot_dir / "progress.json").write_text(
                json.dumps(
                    {
                        "provider_id": PROVIDER_ID,
                        "generated_at": dt.datetime.now().isoformat(),
                        "catalog_url": source_url,
                        "scroll_rounds": scroll_rounds,
                        "records": len(products),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return {"provider_id": PROVIDER_ID, "snapshot_path": str(final_path)}
        finally:
            try:
                context.close()
            except Exception:
                pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def _wait_for_catalog_ready(page, timeout_seconds: int, wait_for_human: bool) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            ready = page.evaluate(
                """
                () => {
                    const hasBlob = !!window.searchProductsData;
                    const bodyText = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
                    const challenge = bodyText.includes('verifica') || bodyText.includes('validaciÃ³n') || bodyText.includes('un momento');
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
        page.wait_for_timeout(1200)


def main() -> int:
    result = crawl_provider()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
