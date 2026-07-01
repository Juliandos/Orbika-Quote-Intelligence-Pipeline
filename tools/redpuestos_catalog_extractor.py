#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote_plus, urlencode, urljoin, urlparse, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.seeded_catalog_support import (
    AUTOS_ONLY_NOTE,
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
    build_searchable_tokens,
    canonical_url,
    dedupe_records,
    entry_urls_from_snapshot,
    latest_snapshot_json,
    load_json,
    normalize_text,
    provider_paths,
    same_host,
    write_snapshot_bundle,
)

PROVIDER_ID = "redpuestos"
DISPLAY_NAME = "Redpuestos"
MAX_PRODUCTS = 50000
MAX_SEED_PAGES = 200
MAX_SCROLL_STEPS_PER_SEED = 260
SCROLL_IDLE_ROUNDS = 10
SCROLL_PAUSE_MS = 1200
POST_CAPTCHA_RECOVERY_MS = 3000
FILTER_QUERY_KEYS = ("groups", "makes", "models")
DEFAULT_ENTRY_URLS = (
    "https://www.imotriz.com/tienda/redpuestos/catalogo/page/results",
    "https://www.imotriz.com/tienda/redpuestos/",
)
EXCLUDE_KEYWORDS = (
    "moto",
    "motoc",
    "camion",
    "camiones",
    "bus",
    "buses",
    "tracto",
    "npr",
    "diesel",
    "agricola",
    "industrial",
)
DISALLOWED_URL_PATTERNS = (
    "/login",
    "/account",
    "/checkout",
    "/cart",
    "/admin",
)
CARD_HINTS = (
    "agregar a cotización",
    "confirmar",
    "agotado",
    "ver detalle",
    "n° de parte",
    "nº de parte",
    "costo de envío",
    "vehículos compatibles",
    "impuesto incluido",
    "entrega:",
    "desde $",
)
CARD_NOISE_PATTERNS = (
    "agregar a cotización",
    "confirmar",
    "agotado",
    "ver detalle",
    "puedes intentar solicitando una cotización para buscar más opciones de compra",
    "costo de envío:",
    "vehículos compatibles",
    "impuesto incluido",
    "cantidad:",
    "entrega:",
    "marca:",
    "n° de parte:",
    "nº de parte:",
    "n de parte:",
)


def get_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/redpuestos_catalog_extractor.py`"
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def detect_browser_executable() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip()
    if configured:
        return configured
    for candidate in ("google-chrome", "google-chrome-stable", "microsoft-edge", "msedge", "chromium"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    if any(pattern in lowered for pattern in DISALLOWED_URL_PATTERNS):
        return True
    return any(keyword in lowered for keyword in EXCLUDE_KEYWORDS)


def page_has_human_verification(page) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body_text = ""
    lowered = (body_text or "").lower()
    return any(
        token in lowered
        for token in (
            "no soy un robot",
            "valida que no eres un robot",
            "para continuar válida que no eres un robot",
            "captcha",
            "recaptcha",
            "verificación humana",
        )
    )


def is_product_detail_url(url: str) -> bool:
    lowered = url.lower()
    return "/producto/" in lowered or "/product/" in lowered


def is_redpuestos_listing_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "/tienda/redpuestos" not in path:
        return False
    if any(token in path for token in ("/producto/", "/product/", "/home")):
        return False
    if "/catalogo/page/results" in path:
        return True
    query = parse_qs(parsed.query)
    return any(key in query for key in FILTER_QUERY_KEYS)

def ensure_listing_surface(page, seed_url: str, notes: list[str]) -> bool:
    """
    Keep the browser on the catalog/listing surface.
    Redpuestos can occasionally jump into a product detail page after captcha or
    a stray click; for this extractor we always want to resume from the seed/list page.
    """
    try:
        current_url = canonical_url(page.url)
    except Exception:
        current_url = page.url
    if not current_url:
        return False
    if current_url == seed_url or is_redpuestos_listing_url(current_url):
        return False
    notes.append(f"Returned from non-listing page to catalog surface: {current_url}")
    try:
        page.goto(seed_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        return True
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Could not return to listing surface from {current_url}: {exc}")
        return False


def wait_for_manual_verification(page, seed_url: str, notes: list[str], timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    notes.append("Validación humana detectada. Resuelve el captcha en la ventana visible y el extractor continuará automáticamente.")
    try:
        restore_scroll_y = int(page.evaluate("window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0"))
    except Exception:
        restore_scroll_y = 0

    def prepare_visible_view() -> None:
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.set_viewport_size({"width": 1440, "height": 900})
        except Exception:
            pass
        try:
            page.evaluate(
                """
                () => {
                  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
                  document.documentElement.scrollTop = 0;
                  document.body.scrollTop = 0;
                  document.documentElement.style.zoom = '0.85';
                  document.body.style.zoom = '0.85';
                  const selectors = [
                    'iframe[src*="recaptcha"]',
                    'iframe[title*="reCAPTCHA"]',
                    'iframe[title*="captcha"]',
                    '[id*="recaptcha"]',
                    '[class*="recaptcha"]',
                    '.g-recaptcha',
                    'input[type="checkbox"]',
                  ];
                  for (const selector of selectors) {
                    for (const el of document.querySelectorAll(selector)) {
                      try {
                        el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
                      } catch (err) {}
                    }
                  }
                }
                """
            )
        except Exception:
            pass
    prepare_visible_view()
    while time.time() < deadline:
        if not page_has_human_verification(page):
            notes.append("La validaci?n humana desapareci? y el extractor continu?.")
            try:
                page.evaluate(f"window.scrollTo({{ top: {restore_scroll_y}, left: 0, behavior: 'instant' }});")
            except Exception:
                pass
            return True
        prepare_visible_view()
        try:
            page.wait_for_timeout(1000)
        except Exception:
            break
        if page.url != seed_url and not page_has_human_verification(page):
            notes.append("La p?gina cambi? despu?s de validar; seguimos con la extracci?n.")
            try:
                page.evaluate(f"window.scrollTo({{ top: {restore_scroll_y}, left: 0, behavior: 'instant' }});")
            except Exception:
                pass
            return True
    notes.append("No se pudo superar la validaci?n humana dentro del tiempo de espera.")
    return False


def build_query_url(base_url: str, **params: str) -> str:
    split = urlsplit(base_url)
    query = parse_qs(split.query)
    for key, value in params.items():
        if value:
            query[key] = [value]
    return canonical_url(urlunsplit((split.scheme, split.netloc, split.path, urlencode(query, doseq=True, quote_via=quote), split.fragment)))


def seed_context_from_url(url: str) -> dict[str, str | None]:
    params = parse_qs(urlparse(url).query)
    return {
        "groups": normalize_text(unquote_plus(params.get("groups", [""])[0])) or None,
        "makes": normalize_text(unquote_plus(params.get("makes", [""])[0])) or None,
        "models": normalize_text(unquote_plus(params.get("models", [""])[0])) or None,
    }


def seed_urls_from_metadata(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> list[str]:
    urls: list[str] = []
    for value in (metadata.get("catalog_root_url"), metadata.get("website")):
        if isinstance(value, str):
            urls.append(value)
    selectors = metadata.get("selectors")
    if isinstance(selectors, dict):
        for key in ("entry_urls", "browser_entry_urls", "seed_urls"):
            value = selectors.get(key)
            if isinstance(value, str):
                urls.append(value)
            elif isinstance(value, list):
                urls.extend([item for item in value if isinstance(item, str)])
    if seed_snapshot:
        urls.extend(entry_urls_from_snapshot(seed_snapshot))
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        normalized = canonical_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def discover_filter_seed_urls(page, host: str) -> list[str]:
    try:
        raw_hrefs = page.locator("a[href]").evaluate_all("(els) => els.map((el) => el.href || el.getAttribute('href')).filter(Boolean)")
    except Exception:
        raw_hrefs = []
    urls: list[str] = []
    seen: set[str] = set()
    for raw_href in raw_hrefs or []:
        absolute = canonical_url(urljoin(page.url, str(raw_href)))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != host:
            continue
        if ignored_url(absolute):
            continue
        if "/catalogo/page/results" not in parsed.path.lower():
            continue
        query = parse_qs(parsed.query)
        if not any(key in query for key in FILTER_QUERY_KEYS):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)
    if urls:
        return urls
    return []


def extract_rendered_card_payloads(page) -> list[dict[str, object]]:
    try:
        payloads = page.evaluate(
            """
            () => {
              const keywords = [
                "agregar a cotización",
                "confirmar",
                "agotado",
                "ver detalle",
                "n° de parte",
                "nº de parte",
                "costo de envío",
                "vehículos compatibles",
                "impuesto incluido",
                "entrega:",
                "desde $",
              ];
              const results = [];
              const elements = [...document.querySelectorAll("article, li, section, div")];
              for (const el of elements) {
                const text = (el.innerText || "").replace(/\u00a0/g, " ").replace(/\\s+\\n/g, "\\n").trim();
                if (!text) continue;
                const lowered = text.toLowerCase();
                if (!keywords.some((keyword) => lowered.includes(keyword))) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width < 150 || rect.height < 120) continue;
                const imgs = [...el.querySelectorAll("img")].map((img) => img.currentSrc || img.src || "").filter(Boolean);
                const links = [...el.querySelectorAll("a")].map((a) => a.href || a.getAttribute("href") || "").filter(Boolean);
                results.push({ text, links, imgs, width: rect.width, height: rect.height });
              }
              return results;
            }
            """
        )
    except Exception:
        payloads = []
    return [payload for payload in payloads or [] if isinstance(payload, dict)]


def is_noise_line(line: str) -> bool:
    lowered = line.lower().strip()
    if not lowered:
        return True
    if any(pattern in lowered for pattern in CARD_NOISE_PATTERNS):
        return True
    if re.fullmatch(r"(?:desde\s*)?\$?[\d\.\,]+", lowered):
        return True
    return lowered in {"-", "•"}


def brand_like_line(line: str) -> bool:
    lowered = line.lower().strip()
    if not lowered:
        return False
    if "marca:" in lowered:
        return True
    if any(token in lowered for token in ("genuine parts", "oem", "track one", "acdelco", "echlin", "quantum")):
        return True
    if line.isupper() and len(line.split()) <= 4 and len(line) <= 40:
        return True
    return len(line.split()) <= 3 and len(line) <= 32 and any(ch.isalpha() for ch in line)


def parse_card_payload(payload: dict[str, object], seed_url: str, host: str) -> ProductRecord | None:
    text = normalize_text(str(payload.get("text") or ""))
    if not text:
        return None
    raw_lines = [normalize_text(line) for line in re.split(r"[\r\n]+", text) if normalize_text(line)]
    if not raw_lines:
        return None

    reference_match = re.search(r"(?:n[°ºo]\s*de\s*parte|n[°ºo]\s*parte|n[°ºo]\s*de\s*pieza)\s*:\s*([^\n]+)", text, re.IGNORECASE)
    reference = normalize_text(reference_match.group(1)) if reference_match else None

    brand = None
    for line in raw_lines:
        if line.lower().startswith("marca:"):
            brand = normalize_text(line.split(":", 1)[1])
            break

    cleaned_lines: list[str] = []
    brand_consumed = False
    for line in raw_lines:
        if is_noise_line(line):
            continue
        if not brand and not brand_consumed and brand_like_line(line):
            brand = line
            brand_consumed = True
            continue
        if brand and not brand_consumed and line == brand:
            brand_consumed = True
            continue
        cleaned_lines.append(line)

    title = cleaned_lines[0] if cleaned_lines else None
    if title and len(cleaned_lines) > 1 and brand_like_line(title) and not reference:
        title = cleaned_lines[1]
    if not title:
        title = reference or brand
    if not title:
        return None

    detail_url = None
    for link in payload.get("links", []) or []:
        if not isinstance(link, str):
            continue
        absolute = canonical_url(urljoin(seed_url, link))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != host or ignored_url(absolute):
            continue
        detail_url = absolute
        if "/producto/" in parsed.path.lower() or "/product/" in parsed.path.lower():
            break

    image_url = None
    for image in payload.get("imgs", []) or []:
        if isinstance(image, str):
            normalized = normalize_text(image)
            if normalized.startswith("http"):
                image_url = normalized
                break

    price_match = re.search(r"(?:desde\s*)?\$\s*([\d\.\,]+)", text, re.IGNORECASE)
    price_text = price_match.group(0) if price_match else None
    tail_description_parts = cleaned_lines[1:] if len(cleaned_lines) > 1 else []
    if price_text and price_text not in tail_description_parts:
        tail_description_parts.insert(0, price_text)
    description = normalize_text(" ".join(tail_description_parts)) or text

    context = seed_context_from_url(seed_url)
    category_name = context.get("groups") or "Redpuestos"
    subcategory_name = context.get("models") or context.get("makes")
    searchable_tokens = build_searchable_tokens(
        title,
        brand,
        reference,
        description,
        context.get("groups"),
        context.get("makes"),
        context.get("models"),
        DISPLAY_NAME,
        seed_url,
    )
    return ProductRecord(
        item_type="product",
        provider_type="product_catalog",
        title=title,
        product_name=title,
        detail_url=detail_url,
        product_url=detail_url,
        category_name=category_name,
        subcategory_name=subcategory_name,
        brand=brand,
        reference=reference,
        sku=None,
        supplier_item_code=reference,
        description=description,
        vehicle_scope="Autos",
        image_url=image_url,
        source_page_url=seed_url,
        page_number=1,
        match_type="manual_confirmation_required",
        match_confidence="medium" if (title or reference) else "low",
        requires_manual_confirmation=True,
        searchable_tokens=searchable_tokens,
    )


def crawl_seed_page(page, seed_url: str, host: str, *, wait_for_human: bool, human_wait_timeout_seconds: int) -> tuple[list[ProductRecord], list[str], list[str], dict[str, object]]:
    coverage: dict[str, object] = {
        "seed_url": seed_url,
        "products_found": 0,
        "product_payloads_seen": 0,
        "scroll_steps": 0,
        "status": "starting",
        "discovered_filter_seeds": [],
    }
    notes: list[str] = []
    records: list[ProductRecord] = []
    seen_keys: set[str] = set()
    discovered_seeds: list[str] = []
    seen_discovered: set[str] = set()
    last_record_count = 0
    last_height = 0
    idle_rounds = 0
    page_closed = False

    try:
        page.goto(seed_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2200)
        try:
            page.wait_for_selector("#store-module-embed-vue-app", timeout=20000)
        except Exception:
            pass
        if wait_for_human and page_has_human_verification(page):
            if not wait_for_manual_verification(page, seed_url, notes, human_wait_timeout_seconds):
                coverage["status"] = "verification_timeout"
                return [], notes, discovered_seeds, coverage
        ensure_listing_surface(page, seed_url, notes)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Navigation warning for {seed_url}: {exc}")
        coverage["status"] = "navigation_failed"
        return [], notes, discovered_seeds, coverage

    while coverage["scroll_steps"] < MAX_SCROLL_STEPS_PER_SEED and idle_rounds < SCROLL_IDLE_ROUNDS:
        try:
            page_payloads = extract_rendered_card_payloads(page)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Card extraction warning for {seed_url}: {exc}")
            page_payloads = []

        for payload in page_payloads:
            record = parse_card_payload(payload, seed_url, host)
            if not record:
                continue
            key = record.detail_url or record.product_url or f"{record.title or record.product_name}:{record.reference or ''}:{record.brand or ''}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            records.append(record)

        if len(records) > last_record_count:
            idle_rounds = 0
        else:
            idle_rounds += 1
        last_record_count = len(records)

        for candidate in discover_filter_seed_urls(page, host):
            if candidate not in seen_discovered:
                seen_discovered.add(candidate)
                discovered_seeds.append(candidate)

        try:
            current_height = page.evaluate("document.body.scrollHeight")
        except Exception:
            current_height = last_height

        if current_height == last_height and idle_rounds > 1:
            try:
                page.mouse.wheel(0, 2500)
            except Exception:
                pass
        else:
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            try:
                page.mouse.wheel(0, 2500)
            except Exception:
                pass

        last_height = current_height
        try:
            page.wait_for_timeout(SCROLL_PAUSE_MS)
        except Exception:
            page_closed = True
            coverage["status"] = "page_closed"
            break
        if wait_for_human and page_has_human_verification(page):
            if not wait_for_manual_verification(page, seed_url, notes, human_wait_timeout_seconds):
                break
            # After captcha resolution, the catalog often needs a few extra
            # seconds to restore lazy-loaded cards before more scrolling works.
            idle_rounds = 0
            last_height = 0
            try:
                page.wait_for_timeout(POST_CAPTCHA_RECOVERY_MS)
            except Exception:
                page_closed = True
                coverage["status"] = "page_closed"
                break
        ensure_listing_surface(page, seed_url, notes)
        coverage["scroll_steps"] = int(coverage["scroll_steps"]) + 1

    if not page_closed:
        try:
            for payload in extract_rendered_card_payloads(page):
                record = parse_card_payload(payload, seed_url, host)
                if not record:
                    continue
                key = record.detail_url or record.product_url or f"{record.title or record.product_name}:{record.reference or ''}:{record.brand or ''}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                records.append(record)
        except Exception:
            pass

    if page_closed:
        notes.append(f"Page closed during crawl of {seed_url}")
        coverage["status"] = "page_closed"
    elif not records:
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = ""
        lowered = body_text.lower()
        if any(token in lowered for token in ("verificaci?n", "confirmaci?n", "human", "robot", "captcha")):
            notes.append(f"Possible human verification on {seed_url}")
            coverage["status"] = "verification_prompt"
        else:
            notes.append(f"No rendered product cards found on {seed_url}")
            coverage["status"] = "no_product_cards"
    else:
        coverage["status"] = "ok"
    coverage["products_found"] = len(records)
    coverage["product_payloads_seen"] = len(seen_keys)
    coverage["discovered_filter_seeds"] = discovered_seeds
    return records, notes, discovered_seeds, coverage


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str], dict[str, object]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    sync_playwright, _ = get_playwright()
    browser_path = detect_browser_executable()
    headed = bool_env("REDPUESTOS_HEADED", default=bool_env("REDPUESTOS_WAIT_FOR_HUMAN"))
    wait_for_human = bool_env("REDPUESTOS_WAIT_FOR_HUMAN", default=headed)
    human_wait_timeout_seconds = int(os.environ.get("REDPUESTOS_HUMAN_WAIT_TIMEOUT_SECONDS", "900"))
    persistent_context = bool_env("REDPUESTOS_PERSISTENT_CONTEXT")
    user_data_dir = Path(os.environ.get("REDPUESTOS_USER_DATA_DIR", str(REPO_ROOT / "local" / "browser_profiles" / "redpuestos")))

    # For redpuestos we always start from the live catalog root and discover
    # additional listing surfaces from the current session only.
    seed_queue = [str(metadata.get("catalog_root_url") or metadata.get("website") or "")]
    seed_queue = [url for url in seed_queue if is_redpuestos_listing_url(url)] or [str(metadata.get("catalog_root_url") or "")]

    notes = [AUTOS_ONLY_NOTE, "Redpuestos requires browser scrolling on the rendered store page; the catalog is discovered from visible cards and filter links."]
    coverage: dict[str, object] = {
        "browser": {
            "headless": not headed,
            "executable_path": browser_path,
            "persistent_context": persistent_context,
            "user_data_dir": str(user_data_dir),
            "wait_for_human": wait_for_human,
        },
        "seed_pages": [],
        "discovered_seed_count": 0,
        "discovered_card_count": 0,
    }

    all_records: list[ProductRecord] = []
    seen_seeds: set[str] = set()
    seen_queue: set[str] = {canonical_url(url) for url in seed_queue if url}

    with sync_playwright() as playwright:
        if persistent_context:
            context = playwright.chromium.launch_persistent_context(
                str(user_data_dir),
                locale="es-CO",
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                headless=not headed,
                executable_path=browser_path,
            )
            browser = None
        else:
            browser_kwargs: dict[str, object] = {"headless": not headed}
            if browser_path:
                browser_kwargs["executable_path"] = browser_path
            browser = playwright.chromium.launch(**browser_kwargs)
            context = browser.new_context(
                locale="es-CO",
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            )

        page = context.new_page()
        page.set_default_timeout(15000)
        if not wait_for_human:
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"} else route.continue_())

        try:
            while seed_queue and len(seen_seeds) < MAX_SEED_PAGES and len(all_records) < MAX_PRODUCTS:
                seed_url = canonical_url(seed_queue.pop(0))
                if seed_url in seen_seeds or ignored_url(seed_url):
                    continue
                if not same_host(seed_url, host):
                    continue
                seen_seeds.add(seed_url)
                seed_records, seed_notes, discovered_seeds, seed_coverage = crawl_seed_page(
                    page,
                    seed_url,
                    host,
                    wait_for_human=wait_for_human,
                    human_wait_timeout_seconds=human_wait_timeout_seconds,
                )
                if seed_coverage.get("status") == "page_closed":
                    notes.append(f"Seed page closed for {seed_url}; stopping this seed and keeping the rest of the queue alive.")
                all_records.extend(seed_records)
                notes.extend(seed_notes)
                coverage["seed_pages"].append(seed_coverage)
                for candidate in discovered_seeds:
                    normalized = canonical_url(candidate)
                    if not is_redpuestos_listing_url(normalized):
                        continue
                    seen_queue.add(normalized)
                    seed_queue.append(normalized)
        finally:
            try:
                context.close()
            finally:
                if browser is not None:
                    browser.close()

    coverage["discovered_seed_count"] = len(seen_seeds)
    coverage["discovered_card_count"] = len(all_records)
    deduped = dedupe_records(all_records, EXCLUDE_KEYWORDS)
    coverage["deduped_record_count"] = len(deduped)
    notes.append(f"Seed pages crawled: {len(seen_seeds)}")
    notes.append(f"Records before dedupe: {len(all_records)}")
    notes.append(f"Records after dedupe: {len(deduped)}")
    notes.append(MANUAL_NOTE)
    return deduped, list(dict.fromkeys(notes)), coverage


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes, coverage = crawl_provider(metadata, seed_snapshot)
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=products,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    payload["catalog_coverage"] = coverage
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


