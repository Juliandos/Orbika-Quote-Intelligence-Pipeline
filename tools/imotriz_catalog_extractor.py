#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlencode, urljoin, urlparse, urlsplit, urlunsplit

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
    extract_meta_content,
    extract_page_title,
    fetch_url,
    iter_json_ld_nodes,
    latest_snapshot_json,
    load_json,
    normalize_text,
    parse_json_ld_blocks,
    parse_product_fallback,
    product_from_json_ld,
    provider_paths,
    same_host,
    write_snapshot_bundle,
)

PROVIDER_ID = "imotriz"
DISPLAY_NAME = "Imotriz"
MAX_MAKE_PAGES = 64
MAX_SCROLL_STEPS_PER_MAKE = 260
SCROLL_IDLE_ROUNDS = 4
SCROLL_PAUSE_MS = 900
DETAIL_FETCH_WORKERS = 6
MAX_PRODUCTS = 50000
MAX_SCROLL_STEPS_PER_MODEL = 100
MAKE_ENTRY_URLS = [
    "https://www.imotriz.com/catalogo/page/results?makes=alfa%20romeo",
    "https://www.imotriz.com/catalogo/page/results?makes=audi",
    "https://www.imotriz.com/catalogo/page/results?makes=bmw",
    "https://www.imotriz.com/catalogo/page/results?makes=cadillac",
    "https://www.imotriz.com/catalogo/page/results?makes=chevrolet",
    "https://www.imotriz.com/catalogo/page/results?makes=chrysler",
    "https://www.imotriz.com/catalogo/page/results?makes=cupra",
    "https://www.imotriz.com/catalogo/page/results?makes=daewoo",
    "https://www.imotriz.com/catalogo/page/results?makes=imotriz",
    "https://www.imotriz.com/catalogo/page/results?makes=hyundai",
    "https://www.imotriz.com/catalogo/page/results?makes=hyosung",
    "https://www.imotriz.com/catalogo/page/results?makes=hummer",
    "https://www.imotriz.com/catalogo/page/results?makes=honda",
    "https://www.imotriz.com/catalogo/page/results?makes=gmc",
    "https://www.imotriz.com/catalogo/page/results?makes=ford",
    "https://www.imotriz.com/catalogo/page/results?makes=fiat",
    "https://www.imotriz.com/catalogo/page/results?makes=dodge",
    "https://www.imotriz.com/catalogo/page/results?makes=datsun",
    "https://www.imotriz.com/catalogo/page/results?makes=land%20rover",
    "https://www.imotriz.com/catalogo/page/results?makes=lancia",
    "https://www.imotriz.com/catalogo/page/results?makes=kia%20besta",
    "https://www.imotriz.com/catalogo/page/results?makes=kia",
    "https://www.imotriz.com/catalogo/page/results?makes=jeep",
    "https://www.imotriz.com/catalogo/page/results?makes=lincoln",
    "https://www.imotriz.com/catalogo/page/results?makes=mazda",
    "https://www.imotriz.com/catalogo/page/results?makes=mercedes%20benz",
    "https://www.imotriz.com/catalogo/page/results?makes=mercedesbenz",
    "https://www.imotriz.com/catalogo/page/results?makes=mercury",
    "https://www.imotriz.com/catalogo/page/results?makes=mini",
    "https://www.imotriz.com/catalogo/page/results?makes=mitsubishi",
    "https://www.imotriz.com/catalogo/page/results?makes=nissan",
    "https://www.imotriz.com/catalogo/page/results?makes=nissan%2Fqashqai",
    "https://www.imotriz.com/catalogo/page/results?makes=opel",
    "https://www.imotriz.com/catalogo/page/results?makes=pontiac",
    "https://www.imotriz.com/catalogo/page/results?makes=ram",
    "https://www.imotriz.com/catalogo/page/results?makes=renault",
    "https://www.imotriz.com/catalogo/page/results?makes=saturn",
    "https://www.imotriz.com/catalogo/page/results?makes=seat",
    "https://www.imotriz.com/catalogo/page/results?makes=sin%20marca",
    "https://www.imotriz.com/catalogo/page/results?makes=skoda",
    "https://www.imotriz.com/catalogo/page/results?makes=ssangyong",
    "https://www.imotriz.com/catalogo/page/results?makes=subaru",
    "https://www.imotriz.com/catalogo/page/results?makes=suzuki",
    "https://www.imotriz.com/catalogo/page/results?makes=toyota",
    "https://www.imotriz.com/catalogo/page/results?makes=volkswagen",
    "https://www.imotriz.com/catalogo/page/results?makes=volvo",
]

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

PRODUCT_PATH_HINTS = ("/producto/",)
DISALLOWED_URL_PATTERNS = (
    "/login",
    "/account",
    "/checkout",
    "/cart",
    "/admin",
)
VEHICLE_TOKENS = (
    "alfa romeo",
    "audi",
    "bmw",
    "cadillac",
    "chevrolet",
    "chrysler",
    "cupra",
    "daewoo",
    "hyundai",
    "honda",
    "ford",
    "fiat",
    "dodge",
    "land rover",
    "kia",
    "jeep",
    "mazda",
    "mercedes",
    "mitsubishi",
    "nissan",
    "opel",
    "renault",
    "subaru",
    "suzuki",
    "toyota",
    "volkswagen",
    "volvo",
)


def get_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Missing Playwright dependency. Run this extractor with "
            "`uv run --with playwright python tools/imotriz_catalog_extractor.py` "
            "and install Chromium if needed with "
            "`uv run --with playwright python -m playwright install chromium`."
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def detect_browser_executable() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSER_PATH", "").strip()
    if configured:
        return configured
    for candidate in (
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "msedge",
        "chromium",
    ):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def is_valid_http_url(url: str) -> bool:
    if not url.startswith("http"):
        return False
    if any(ch in url for ch in (" ", "\t", "\r", "\n", "'", '"', "{", "}", "<", ">")):
        return False
    return True


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    if any(pattern in lowered for pattern in DISALLOWED_URL_PATTERNS):
        return True
    return any(keyword in lowered for keyword in EXCLUDE_KEYWORDS)


def extract_section_button_texts(page, section_label: str) -> list[str]:
    try:
        return page.evaluate(
            """
            (labelText) => {
              const labels = [...document.querySelectorAll("label")];
              const label = labels.find((el) => el.textContent.trim() === labelText);
              if (!label || !label.parentElement) return [];
              return [...label.parentElement.querySelectorAll("button")]
                .map((button) => (button.textContent || "").replace(/\\s+/g, " ").trim())
                .filter(Boolean);
            }
            """,
            section_label,
        )
    except Exception:
        return []


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
        )
    )


def wait_for_manual_verification(page, seed_url: str, notes: list[str], timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    notes.append(
        "Validación humana detectada. Abre el captcha en la ventana visible, "
        "resuélvelo y el extractor continuará solo."
    )

    def force_top_view() -> None:
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.evaluate(
                """
                () => {
                  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
                  document.documentElement.scrollTop = 0;
                  document.body.scrollTop = 0;
                }
                """
            )
        except Exception:
            pass

    force_top_view()
    while time.time() < deadline:
        if not page_has_human_verification(page):
            notes.append("La validación humana desapareció y el extractor continuó.")
            return True
        force_top_view()
        try:
            page.wait_for_timeout(1000)
        except Exception:
            break
        if page.url != seed_url and not page_has_human_verification(page):
            notes.append("La página cambió después de validar; seguimos con la extracción.")
            return True
    notes.append("No se pudo superar la validación humana dentro del tiempo de espera.")
    return False


def model_name_from_url(url: str) -> str | None:
    params = parse_qs(urlparse(url).query)
    raw = params.get("models", [""])[0]
    if not raw:
        return None
    return normalize_text(unquote_plus(raw)) or None


def build_query_url(base_url: str, **params: str) -> str:
    split = urlsplit(base_url)
    query = parse_qs(split.query)
    for key, value in params.items():
        if value:
            query[key] = [value]
    return canonical_url(urlunsplit((split.scheme, split.netloc, split.path, urlencode(query, doseq=True), split.fragment)))


def discover_model_seed_urls(page, make_url: str, host: str) -> list[str]:
    make_name = make_name_from_url(make_url)
    if not make_name:
        return []
    model_names = extract_section_button_texts(page, "Modelo Vehículo")
    seen: set[str] = set()
    urls: list[str] = []
    for model_name in model_names:
        normalized_model = normalize_text(model_name).lower()
        if not normalized_model:
            continue
        candidate = build_query_url(make_url, makes=make_name.lower(), models=normalized_model)
        parsed = urlparse(candidate)
        if parsed.netloc.lower() != host:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def make_name_from_url(url: str) -> str | None:
    params = parse_qs(urlparse(url).query)
    raw = params.get("makes", [""])[0]
    if not raw:
        return None
    return normalize_text(unquote_plus(raw)) or None


def product_like_url(url: str) -> bool:
    parsed = urlparse(url)
    lowered = parsed.path.lower()
    return any(hint in lowered for hint in PRODUCT_PATH_HINTS) and not ignored_url(url)


def first_text(value: object) -> str | None:
    if isinstance(value, str):
        normalized = normalize_text(value)
        return normalized or None
    if isinstance(value, list):
        for item in value:
            text = first_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("name", "text", "value", "Value", "label", "@id"):
            if key in value:
                text = first_text(value.get(key))
                if text:
                    return text
    return None


def first_image_url(value: object) -> str | None:
    if isinstance(value, str):
        normalized = normalize_text(value)
        return normalized if normalized.startswith("http") else None
    if isinstance(value, list):
        for item in value:
            image_url = first_image_url(item)
            if image_url:
                return image_url
    if isinstance(value, dict):
        for key in ("contentUrl", "url", "@id", "imageUrl"):
            image_url = first_image_url(value.get(key))
            if image_url:
                return image_url
    return None


def infer_match_type(
    title: str | None,
    category_name: str | None,
    description: str | None,
    reference: str | None,
    compatibility_text: str | None = None,
) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, category_name, description, compatibility_text])).lower()
    if reference:
        return "exact_reference", "high", False
    if any(token in allowed_text for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", True
    return "category_only", "medium", True


def extract_product_urls_from_page(page, host: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    selectors = [
        'a[href*="/producto/"]',
        'a[href*="/product/"]',
        'a[href*="/producto-"]',
    ]
    for selector in selectors:
        try:
            raw_urls = page.locator(selector).evaluate_all(
                "(els) => els.map((el) => el.href || el.getAttribute('href')).filter(Boolean)"
            )
        except Exception:
            raw_urls = []
        for raw_url in raw_urls or []:
            absolute = canonical_url(urljoin(page.url, str(raw_url)))
            parsed = urlparse(absolute)
            if parsed.netloc.lower() != host:
                continue
            if not product_like_url(absolute) or ignored_url(absolute):
                continue
            if absolute not in seen:
                urls.append(absolute)
                seen.add(absolute)

    if urls:
        return urls

    try:
        html = page.content()
    except Exception:
        return urls
    for match in re.findall(r"href=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE):
        absolute = canonical_url(urljoin(page.url, match))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != host:
            continue
        if not product_like_url(absolute) or ignored_url(absolute):
            continue
        if absolute not in seen:
            urls.append(absolute)
            seen.add(absolute)
    return urls


def parse_product_page(
    url: str,
    html: str,
    source_page_url: str,
    make_name: str | None,
    model_name: str | None = None,
) -> list[ProductRecord]:
    nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)]
    meta_description = extract_meta_content(html, "description")
    meta_image = extract_meta_content(html, "og:image")
    page_title = extract_page_title(html)
    records = product_from_json_ld(
        url=url,
        page_title=page_title,
        description=meta_description,
        image_url=meta_image,
        source_page_url=source_page_url,
        json_ld_nodes=nodes,
        infer_match_type=infer_match_type,
    )
    if not records:
        fallback = parse_product_fallback(
            url=url,
            html=html,
            source_page_url=source_page_url,
            category_only_mode=False,
            infer_match_type=infer_match_type,
        )
        if fallback is None:
            return []
        records = [fallback]

    for record in records:
        record.provider_type = "product_catalog"
        record.vehicle_scope = record.vehicle_scope or "Autos"
        if make_name:
            record.searchable_tokens = build_searchable_tokens(
                *record.searchable_tokens,
                make_name,
                "imotriz",
                "marketplace",
            )
            if not record.category_name:
                record.category_name = make_name
        if model_name:
            record.searchable_tokens = build_searchable_tokens(
                *record.searchable_tokens,
                model_name,
                "imotriz",
                "marketplace",
            )
            if not record.subcategory_name:
                record.subcategory_name = model_name
    return records


def fetch_product_record(url: str, source_page_url: str, make_name: str | None) -> list[ProductRecord]:
    model_name = model_name_from_url(source_page_url)
    try:
        final_url, raw, headers = fetch_url(url)
    except Exception as exc:  # noqa: BLE001
        return [
            ProductRecord(
                item_type="product",
                provider_type="product_catalog",
                product_name=Path(urlparse(url).path).name or url,
                product_url=url,
                detail_url=url,
                source_page_url=source_page_url,
                category_name=make_name,
                subcategory_name=model_name,
                description=f"Fetch warning: {exc}",
                vehicle_scope="Autos",
                match_type="manual_confirmation_required",
                match_confidence="low",
                requires_manual_confirmation=True,
                searchable_tokens=build_searchable_tokens(url, make_name, model_name, "imotriz"),
            )
        ]
    html = decode_html(raw, headers)
    return parse_product_page(final_url, html, source_page_url, make_name, model_name)


def crawl_catalog_surface(
    page,
    seed_url: str,
    host: str,
    *,
    max_scroll_steps: int,
    collect_model_urls: bool,
    wait_for_human: bool = False,
    human_wait_timeout_seconds: int = 900,
) -> tuple[list[str], dict[str, object], list[str], list[str]]:
    seen: set[str] = set()
    notes: list[str] = []
    make_name = make_name_from_url(seed_url)
    model_name = model_name_from_url(seed_url)
    discovered_model_urls: list[str] = []
    scroll_steps = 0
    idle_rounds = 0
    last_link_count = 0
    last_height = 0

    try:
        page.goto(seed_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        try:
            page.wait_for_selector("#catalog-embed-vue-app", timeout=20000)
        except Exception:
            pass
        if wait_for_human and page_has_human_verification(page):
            if not wait_for_manual_verification(page, seed_url, notes, human_wait_timeout_seconds):
                return [], {
                    "seed_url": seed_url,
                    "make_name": make_name,
                    "model_name": model_name,
                    "product_links": 0,
                    "discovered_model_urls": 0,
                    "scroll_steps": 0,
                    "seed_type": "make" if collect_model_urls else "model",
                    "status": "verification_timeout",
                }, notes, discovered_model_urls
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Navigation warning for {seed_url}: {exc}")
        return [], {
            "seed_url": seed_url,
            "make_name": make_name,
            "model_name": model_name,
            "product_links": 0,
            "discovered_model_urls": 0,
            "scroll_steps": 0,
            "seed_type": "make" if collect_model_urls else "model",
            "status": "navigation_failed",
        }, notes, discovered_model_urls

    if collect_model_urls:
        discovered_model_urls = discover_model_seed_urls(page, seed_url, host)

    while scroll_steps < max_scroll_steps and idle_rounds < SCROLL_IDLE_ROUNDS:
        current_links = extract_product_urls_from_page(page, host)
        current_count = len(current_links)
        if current_count > last_link_count:
            idle_rounds = 0
        else:
            idle_rounds += 1
        seen.update(current_links)
        last_link_count = max(last_link_count, current_count)

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
        page.wait_for_timeout(SCROLL_PAUSE_MS)
        if wait_for_human and page_has_human_verification(page):
            if not wait_for_manual_verification(page, seed_url, notes, human_wait_timeout_seconds):
                break
        scroll_steps += 1

    if not seen:
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = ""
        lowered = body_text.lower()
        if any(token in lowered for token in ("verificacion", "confirmacion", "human", "robot", "captcha")):
            notes.append(f"Possible human verification on {seed_url}")
            status = "verification_prompt"
        else:
            notes.append(f"No product links found on {seed_url}")
            status = "no_product_links"
    else:
        status = "ok"

    coverage = {
        "seed_url": seed_url,
        "make_url": seed_url,
        "make_name": make_name,
        "model_name": model_name,
        "product_links": len(seen),
        "discovered_model_urls": len(discovered_model_urls),
        "scroll_steps": scroll_steps,
        "seed_type": "make" if collect_model_urls else "model",
        "status": status,
    }
    return sorted(seen), coverage, notes, discovered_model_urls


def collect_make_urls(metadata: dict[str, object]) -> list[str]:
    urls: list[str] = []
    catalog = metadata.get("catalog")
    if isinstance(catalog, dict):
        for value in catalog.get("entry_urls", []) or []:
            if isinstance(value, str):
                urls.append(value)
    selectors = metadata.get("selectors")
    if isinstance(selectors, dict):
        for key in ("brand_entry_urls", "catalog_entry_urls", "make_entry_urls"):
            value = selectors.get(key)
            if isinstance(value, str):
                urls.append(value)
            elif isinstance(value, list):
                urls.extend([item for item in value if isinstance(item, str)])
    urls.extend(MAKE_ENTRY_URLS)

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not is_valid_http_url(url):
            continue
        normalized = canonical_url(url)
        parsed = urlparse(normalized)
        if parsed.netloc.lower() != "www.imotriz.com":
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str], dict[str, object]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    make_urls = collect_make_urls(metadata)

    sync_playwright, PlaywrightTimeoutError = get_playwright()
    browser_path = detect_browser_executable()
    headed = os.environ.get("IMOTRIZ_HEADED", "").strip().lower() in {"1", "true", "yes", "on"}
    wait_for_human_env = os.environ.get("IMOTRIZ_WAIT_FOR_HUMAN", "").strip().lower()
    wait_for_human = wait_for_human_env in {"1", "true", "yes", "on"} or headed
    human_wait_timeout_seconds = int(os.environ.get("IMOTRIZ_HUMAN_WAIT_TIMEOUT_SECONDS", "900"))
    browser_options = {"headless": not headed}
    if browser_path:
        browser_options["executable_path"] = browser_path

    all_product_urls: list[tuple[str, str | None, str | None]] = []
    notes = [
        AUTOS_ONLY_NOTE,
        "Imotriz requires browser scrolling on brand pages; the catalog is discovered from rendered DOM anchors and product pages are enriched through JSON-LD.",
    ]
    coverage: dict[str, object] = {
        "make_pages": [],
        "model_pages": [],
        "browser": {
            "headless": not headed,
            "executable_path": browser_path,
            "wait_for_human": wait_for_human,
        },
        "discovered_make_count": 0,
        "discovered_model_count": 0,
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**browser_options)
        context = browser.new_context(
            locale="es-CO",
            viewport={"width": 1600, "height": 2200},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(15000)
        if not wait_for_human:
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "media", "font"}
                else route.continue_(),
            )

        try:
            for make_url in make_urls[:MAX_MAKE_PAGES]:
                if len(all_product_urls) >= MAX_PRODUCTS:
                    break
                product_urls, make_coverage, make_notes, _ = crawl_catalog_surface(
                    page,
                    make_url,
                    host,
                    max_scroll_steps=MAX_SCROLL_STEPS_PER_MAKE,
                    collect_model_urls=False,
                    wait_for_human=wait_for_human,
                    human_wait_timeout_seconds=human_wait_timeout_seconds,
                )
                coverage["make_pages"].append(make_coverage)
                notes.extend(make_notes)
                for product_url in product_urls:
                    all_product_urls.append((product_url, make_url, make_coverage.get("make_name")))
        finally:
            context.close()
            browser.close()

    coverage["discovered_make_count"] = len(coverage["make_pages"])
    unique_product_urls: list[tuple[str, str, str | None]] = []
    seen_product_urls: set[str] = set()
    for product_url, source_make_url, make_name in all_product_urls:
        if product_url in seen_product_urls:
            continue
        seen_product_urls.add(product_url)
        unique_product_urls.append((product_url, source_make_url, make_name))

    coverage["discovered_product_links"] = len(unique_product_urls)

    records: list[ProductRecord] = []
    if unique_product_urls:
        with ThreadPoolExecutor(max_workers=DETAIL_FETCH_WORKERS) as executor:
            futures = {
                executor.submit(fetch_product_record, product_url, source_make_url, make_name): product_url
                for product_url, source_make_url, make_name in unique_product_urls
            }
            for future in as_completed(futures):
                try:
                    records.extend(future.result())
                except PlaywrightTimeoutError as exc:
                    notes.append(f"Playwright timeout while processing product page: {exc}")
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"Product detail warning: {exc}")
                if len(records) >= MAX_PRODUCTS:
                    break

    coverage["record_count_before_dedupe"] = len(records)
    deduped = dedupe_records(records, EXCLUDE_KEYWORDS)
    coverage["record_count_after_dedupe"] = len(deduped)
    notes.append(f"Make pages crawled: {len(coverage['make_pages'])}")
    notes.append(f"Model pages crawled: {len(coverage['model_pages'])}")
    notes.append(f"Product links discovered: {len(unique_product_urls)}")
    notes.append(f"Records before dedupe: {len(records)}")
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


