#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
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
    default_category_like_url,
    default_product_like_url,
    entry_urls_from_snapshot,
    extract_links,
    extract_meta_content,
    extract_page_title,
    guess_page_number,
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

PROVIDER_ID = 'imotrizsolucionesautomotrices'
DISPLAY_NAME = 'Imotriz Soluciones Automotrices'
ROOT_URL = 'https://www.imotriz.com/tienda/solucionesautomotrices/catalogo'
ENTRY_URLS = (
    ROOT_URL,
    'https://www.imotriz.com/tienda/solucionesautomotrices/',
    'https://www.imotriz.com/tienda/solucionesautomotrices/catalogo/',
)

EXCLUDE_KEYWORDS = (
    'moto', 'motoc', 'camion', 'camiones', 'bus', 'buses', 'tracto', 'npr', 'diesel', 'agricola', 'industrial',
)
VEHICLE_TOKENS = (
    'chevrolet', 'mazda', 'renault', 'kia', 'hyundai', 'nissan', 'toyota', 'ford', 'volkswagen',
)
CARD_NOISE = (
    'read more', 'ver más', 'ver mas', 'agregar', 'add to cart', 'cotizar', 'confirmar',
    'vehículos compatibles', 'vehiculos compatibles', 'costo de envío', 'costo de envio', 'entrega:',
    'impuesto incluido',
)
CHALLENGE_MARKERS = ('verifica', 'verification', 'verify', 'captcha', 'un momento', 'momento', 'human', 'robot', 'solicitud', 'waiting')
DISALLOWED_URL_PATTERNS = (
    '/login',
    '/account',
    '/checkout',
    '/cart',
    '/admin',
    '/feed/',
    '.rss',
    '.xml',
    '/home/page/',
    '/home/cotizacion',
    '/credit/page/',
    '/solicitudcredito',
    '/software-talleres',
    '/info/',
)

SNAPSHOT_DATE = os.environ.get('SNAPSHOT_DATE') or date.today().isoformat()
BASE_DIR = Path('supplier_catalog/providers') / PROVIDER_ID
SNAPSHOT_DIR = BASE_DIR / 'snapshots' / SNAPSHOT_DATE
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

MAX_SEED_PAGES = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_MAX_SEED_PAGES', '1000'))
MAX_PRODUCTS = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_MAX_PRODUCTS', '25000'))
MAX_SCROLL_STEPS = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_MAX_SCROLL_STEPS', '60'))
SCROLL_PAUSE_MS = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_SCROLL_PAUSE_MS', '1100'))
HUMAN_WAIT_TIMEOUT_SECONDS = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_HUMAN_WAIT_TIMEOUT_SECONDS', '900'))
PAGE_WAIT_SECONDS = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_PAGE_WAIT_SECONDS', '45'))
PRODUCT_LOG_EVERY = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_PRODUCT_LOG_EVERY', '25'))
PROGRESS_EVERY = int(os.environ.get('IMOTRIZSOLUCIONESAUTOMOTRICES_PROGRESS_EVERY', '25'))


def log_event(event: str, **payload: object) -> None:
    print(json.dumps({'event': event, **payload}, ensure_ascii=False), flush=True)


def get_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            'Missing Playwright dependency. Run this extractor with `uv run --with playwright python tools/imotrizsolucionesautomotrices_catalog_extractor.py`'
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def detect_browser_executable() -> str | None:
    configured = os.environ.get('PLAYWRIGHT_BROWSER_PATH', '').strip()
    if configured:
        return configured
    for candidate in ('google-chrome', 'google-chrome-stable', 'microsoft-edge', 'msedge', 'chromium'):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, '').strip().lower()
    if not raw:
        return default
    return raw in {'1', 'true', 'yes', 'on'}


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    if any(pattern in lowered for pattern in DISALLOWED_URL_PATTERNS):
        return True
    return any(keyword in lowered for keyword in EXCLUDE_KEYWORDS)


def is_valid_http_url(url: str) -> bool:
    if not url.startswith('http'):
        return False
    if any(ch in url for ch in (' ', '\t', '\r', '\n', "'", '"', '{', '}', '<', '>')):
        return False
    return True


def page_has_human_verification(page) -> bool:
    try:
        body_text = page.locator('body').inner_text(timeout=2000)
    except Exception:
        body_text = ''
    lowered = (body_text or '').lower()
    return any(token in lowered for token in CHALLENGE_MARKERS)


def wait_for_manual_verification(page, seed_url: str, notes: list[str], timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    notes.append(
        'Validación humana detectada. Resuelve el captcha o el reto visible en la ventana actual y el extractor continuará automáticamente.'
    )
    try:
        restore_scroll_y = int(page.evaluate('window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0'))
    except Exception:
        restore_scroll_y = 0

    def prepare_visible_view() -> None:
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.set_viewport_size({'width': 1440, 'height': 900})
        except Exception:
            pass
        try:
            page.evaluate(
                """
                () => {
                  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
                  document.documentElement.scrollTop = 0;
                  document.body.scrollTop = 0;
                  document.documentElement.style.zoom = '0.9';
                  document.body.style.zoom = '0.9';
                }
                """
            )
        except Exception:
            pass

    prepare_visible_view()
    while time.time() < deadline:
        if not page_has_human_verification(page):
            notes.append('La validación humana desapareció y el extractor continuó.')
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
    notes.append('Timeout esperando la validación humana; el extractor siguió con lo que pudo recuperar.')
    return False


def dismiss_popups(page) -> None:
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
                locator.click(timeout=1000, force=True)
                page.wait_for_timeout(300)
        except Exception:
            continue


def normalize_candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in (text or '').splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        lower = line.lower()
        if any(noise in lower for noise in CARD_NOISE):
            continue
        if len(line) < 3:
            continue
        lines.append(line)
    return lines


def infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = ' '.join(filter(None, [title, category_name, description, reference])).lower()
    if any(token in allowed_text for token in VEHICLE_TOKENS):
        return 'vehicle_compatible', 'medium', True
    if reference:
        return 'vehicle_compatible', 'medium', True
    return 'category_only', 'medium', True


def extract_rendered_card_payloads(page) -> list[dict[str, str]]:
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
        href = str(payload.get('href') or '')
        text = str(payload.get('text') or '')
        title = str(payload.get('title') or '')
        aria = str(payload.get('aria') or '')
        image = str(payload.get('image') or '')
        if not href:
            continue
        if image == '' and len(text) < 12 and not default_product_like_url(href) and not default_category_like_url(href):
            continue
        key = (href, text[:80])
        if key in seen:
            continue
        seen.add(key)
        results.append({'href': href, 'text': text, 'title': title, 'aria': aria, 'image': image})
    return results


def build_card_record(payload: dict[str, str], source_page_url: str, host: str) -> ProductRecord | None:
    href = canonical_url(payload.get('href') or '')
    if not href or not same_host(href, host) or ignored_url(href):
        return None

    lines = normalize_candidate_lines(payload.get('text') or '')
    if not lines:
        lines = normalize_candidate_lines(' '.join(filter(None, [payload.get('title'), payload.get('aria')])))
    if not lines:
        return None

    title = lines[0]
    if title.lower() in {'read more', 'ver más', 'ver mas', 'más información', 'mas información'}:
        return None

    description = ' '.join(lines[1:4]).strip()
    image_url = payload.get('image') or None
    text_lower = f"{title} {description}".lower()
    strong_product_signals = bool(
        any(token in text_lower for token in VEHICLE_TOKENS)
        or re.search(r'\b(?:AT-\d+[A-Z]?|PF:\([^)]+\)|PF:\s*[A-Za-z0-9\-\/]+|[A-Z]{2,}\d{2,}[A-Z0-9\-]*)\b', f"{title} {description}", re.IGNORECASE)
    )
    marketing_noise = (
        'al utilizar imotriz',
        'solicitar cotización',
        'solicitar cotizacion',
        'colombia méxico',
        'colombia mexico',
        'ecuador costa rica',
        'mi cuenta',
        'iniciar sesión',
        'iniciar sesion',
        'carrito',
        'home',
        'catalogo',
    )
    if any(noise in text_lower for noise in marketing_noise):
        return None
    if not default_product_like_url(href) and not strong_product_signals:
        return None

    reference_match = re.search(
        r'\b(?:AT-\d+[A-Z]?|PF:\([^)]+\)|PF:\s*[A-Za-z0-9\-\/]+|[A-Z]{2,}\d{2,}[A-Z0-9\-]*)\b',
        f'{title} {description}',
        re.IGNORECASE,
    )
    reference = reference_match.group(0).strip() if reference_match else None
    match_type, match_confidence, requires_manual_confirmation = infer_match_type(title, None, description, reference)

    return ProductRecord(
        item_type='product',
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
        vehicle_scope='autos',
        image_url=image_url,
        source_page_url=source_page_url,
        page_number=guess_page_number(source_page_url),
        match_type=match_type,
        match_confidence=match_confidence,
        requires_manual_confirmation=requires_manual_confirmation,
        searchable_tokens=build_searchable_tokens(title, description, reference),
    )


def extract_detail_records(page, source_url: str) -> list[ProductRecord]:
    html = page.content()
    page_title = extract_page_title(html)
    meta_description = extract_meta_content(html, 'description')
    meta_image = extract_meta_content(html, 'og:image')
    json_ld_nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)]
    records = product_from_json_ld(
        url=source_url,
        page_title=page_title,
        description=meta_description,
        image_url=meta_image,
        source_page_url=source_url,
        json_ld_nodes=json_ld_nodes,
        infer_match_type=infer_match_type,
    )
    if records:
        return records
    fallback = parse_product_fallback(
        url=source_url,
        html=html,
        source_page_url=source_url,
        category_only_mode=False,
        infer_match_type=infer_match_type,
    )
    return [fallback] if fallback else []


def discover_internal_urls(page, host: str, source_url: str) -> list[str]:
    html = page.content()
    discovered: list[str] = []
    for link in extract_links(html, source_url):
        if not is_valid_http_url(link) or ignored_url(link):
            continue
        if not same_host(link, host):
            continue
        if default_product_like_url(link) or default_category_like_url(link) or '/tienda/solucionesautomotrices' in link.lower():
            discovered.append(canonical_url(link))
    return list(dict.fromkeys(discovered))


def scroll_listing(page, wait_for_human: bool, notes: list[str], seed_url: str) -> None:
    stable_rounds = 0
    last_height = -1
    for _ in range(MAX_SCROLL_STEPS):
        try:
            height = int(page.evaluate('document.body.scrollHeight'))
        except Exception:
            height = -1
        if height == last_height:
            stable_rounds += 1
        else:
            stable_rounds = 0
        if stable_rounds >= 3:
            break
        try:
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(SCROLL_PAUSE_MS)
        except Exception:
            break
        last_height = height
        dismiss_popups(page)
        if wait_for_human and page_has_human_verification(page):
            if not wait_for_manual_verification(page, seed_url, notes, HUMAN_WAIT_TIMEOUT_SECONDS):
                break
            try:
                page.wait_for_timeout(2000)
            except Exception:
                break



def scroll_until_product_growth_stops(page, pause_ms: int, max_rounds: int = 80) -> int:
    """Scroll until the visible inventory stops increasing."""
    previous_count = -1
    stable_rounds = 0
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        try:
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.mouse.wheel(0, 2400)
        except Exception:
            break
        try:
            page.wait_for_timeout(pause_ms)
        except Exception:
            break
        current_count = len(extract_rendered_card_payloads(page))
        if current_count <= previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_count = current_count
        if stable_rounds >= 3:
            break
    return rounds
def crawl_seed_page(
    page,
    seed_url: str,
    host: str,
    *,
    wait_for_human: bool,
    human_wait_timeout_seconds: int,
) -> tuple[list[ProductRecord], list[str], list[str], dict[str, object]]:
    notes: list[str] = []
    records: list[ProductRecord] = []
    discovered_urls: list[str] = []
    coverage: dict[str, object] = {
        'seed_url': seed_url,
        'status': 'pending',
        'scroll_steps': 0,
        'records_found': 0,
        'links_found': 0,
        'page_title': '',
        'challenge_detected': False,
    }

    try:
        page.goto(seed_url, wait_until='domcontentloaded', timeout=60000)
        try:
            page.wait_for_load_state('networkidle', timeout=PAGE_WAIT_SECONDS * 1000)
        except Exception:
            pass
        dismiss_popups(page)
        if wait_for_human and page_has_human_verification(page):
            coverage['challenge_detected'] = True
            wait_for_manual_verification(page, seed_url, notes, human_wait_timeout_seconds)
            dismiss_popups(page)
        try:
            page.wait_for_load_state('networkidle', timeout=15000)
        except Exception:
            pass
        scroll_until_product_growth_stops(page, pause_ms=SCROLL_PAUSE_MS, max_rounds=MAX_SCROLL_STEPS)
        dismiss_popups(page)
        try:
            page.wait_for_load_state('networkidle', timeout=15000)
        except Exception:
            pass
        scroll_listing(page, wait_for_human, notes, seed_url)
        coverage['scroll_steps'] = MAX_SCROLL_STEPS
        html = page.content()
        coverage['page_title'] = extract_page_title(html)

        if default_product_like_url(page.url):
            records.extend(extract_detail_records(page, page.url))

        for payload in extract_rendered_card_payloads(page):
            record = build_card_record(payload, seed_url, host)
            if record:
                records.append(record)

        discovered_urls.extend(discover_internal_urls(page, host, seed_url))
        coverage['links_found'] = len(discovered_urls)

        for _ in range(5):
            clicked = False
            for selector in (
                "a[rel='next']",
                "button[rel='next']",
                "nav a:has-text('Next')",
                "nav a:has-text('Siguiente')",
                "nav button:has-text('Next')",
                "nav button:has-text('Siguiente')",
            ):
                try:
                    locator = page.locator(selector).first
                    if locator.count() and locator.is_visible(timeout=500):
                        locator.click(timeout=2000, force=True)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                break
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            dismiss_popups(page)
            if wait_for_human and page_has_human_verification(page):
                coverage['challenge_detected'] = True
                if not wait_for_manual_verification(page, seed_url, notes, human_wait_timeout_seconds):
                    break

        for payload in extract_rendered_card_payloads(page):
            record = build_card_record(payload, seed_url, host)
            if record:
                records.append(record)

        discovered_urls.extend(discover_internal_urls(page, host, seed_url))
        coverage['links_found'] = len(discovered_urls)

        if records:
            coverage['status'] = 'ok'
        else:
            body_text = ''
            try:
                body_text = page.locator('body').inner_text(timeout=3000)
            except Exception:
                pass
            lowered = (body_text or '').lower()
            if any(token in lowered for token in CHALLENGE_MARKERS):
                coverage['status'] = 'verification_prompt'
                notes.append(f'Possible human verification on {seed_url}')
            else:
                coverage['status'] = 'no_records'
                notes.append(f'No rendered product cards found on {seed_url}')

        coverage['records_found'] = len(records)
        return records, notes, list(dict.fromkeys(discovered_urls)), coverage
    except Exception as exc:  # noqa: BLE001
        notes.append(f'crawl_failed:{seed_url}:{type(exc).__name__}:{exc}')
        coverage['status'] = 'error'
        coverage['error'] = f'{type(exc).__name__}: {exc}'
        return records, notes, discovered_urls, coverage


def write_progress(snapshot_dir: Path, payload: dict[str, object]) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / 'progress.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str], dict[str, object]]:
    host = urlparse(str(metadata.get('website') or metadata.get('catalog_root_url') or '')).netloc.lower()
    sync_playwright, _ = get_playwright()
    browser_path = detect_browser_executable()
    headed = bool_env('IMOTRIZSOLUCIONESAUTOMOTRICES_HEADED', default=bool_env('IMOTRIZSOLUCIONESAUTOMOTRICES_WAIT_FOR_HUMAN'))
    wait_for_human = bool_env('IMOTRIZSOLUCIONESAUTOMOTRICES_WAIT_FOR_HUMAN', default=headed)
    persistent_context = bool_env('IMOTRIZSOLUCIONESAUTOMOTRICES_PERSISTENT_CONTEXT')
    user_data_dir = Path(
        os.environ.get(
            'IMOTRIZSOLUCIONESAUTOMOTRICES_USER_DATA_DIR',
            str(REPO_ROOT / 'local' / 'browser_profiles' / 'imotrizsolucionesautomotrices'),
        )
    )

    seed_queue: list[str] = []
    for url in [str(metadata.get('catalog_root_url') or metadata.get('website') or '')] + list(ENTRY_URLS) + entry_urls_from_snapshot(seed_snapshot or {}):
        if not url or not is_valid_http_url(url):
            continue
        normalized = canonical_url(url)
        if ignored_url(normalized) or not same_host(normalized, host):
            continue
        if normalized not in seed_queue:
            seed_queue.append(normalized)

    notes = [
        AUTOS_ONLY_NOTE,
        'Extractor browser-assisted: usa una sola ventana, conserva la posición actual cuando aparece validación humana y registra progreso intermedio.',
    ]
    coverage: dict[str, object] = {
        'browser': {
            'headless': not headed,
            'executable_path': browser_path,
            'persistent_context': persistent_context,
            'user_data_dir': str(user_data_dir),
            'wait_for_human': wait_for_human,
        },
        'seed_pages': [],
        'discovered_seed_count': 0,
        'discovered_record_count': 0,
        'discovered_url_count': 0,
    }

    all_records: list[ProductRecord] = []
    seen_seeds: set[str] = set()
    seen_queue: set[str] = set(seed_queue)
    discovered_urls: set[str] = set()

    with sync_playwright() as playwright:
        if persistent_context:
            context = playwright.chromium.launch_persistent_context(
                str(user_data_dir),
                locale='es-CO',
                viewport={'width': 1440, 'height': 900},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
                headless=not headed,
                executable_path=browser_path,
            )
            browser = None
        else:
            browser_kwargs: dict[str, object] = {'headless': not headed}
            if browser_path:
                browser_kwargs['executable_path'] = browser_path
            browser = playwright.chromium.launch(**browser_kwargs)
            context = browser.new_context(
                locale='es-CO',
                viewport={'width': 1440, 'height': 900},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            )

        page = context.new_page()
        page.set_default_timeout(15000)
        if not wait_for_human:
            try:
                page.route(
                    '**/*',
                    lambda route: route.abort()
                    if route.request.resource_type in {'image', 'media', 'font'}
                    else route.continue_(),
                )
            except Exception:
                pass

        try:
            while seed_queue and len(seen_seeds) < MAX_SEED_PAGES and len(all_records) < MAX_PRODUCTS:
                seed_url = canonical_url(seed_queue.pop(0))
                if seed_url in seen_seeds or ignored_url(seed_url):
                    continue
                if not same_host(seed_url, host):
                    continue

                seen_seeds.add(seed_url)
                log_event('imotrizsolucionesautomotrices_seed', seed_url=seed_url, seen=len(seen_seeds), queue=len(seed_queue))
                seed_records, seed_notes, urls, seed_coverage = crawl_seed_page(
                    page,
                    seed_url,
                    host,
                    wait_for_human=wait_for_human,
                    human_wait_timeout_seconds=HUMAN_WAIT_TIMEOUT_SECONDS,
                )
                all_records.extend(seed_records)
                notes.extend(seed_notes)
                coverage['seed_pages'].append(seed_coverage)
                for candidate in urls:
                    normalized = canonical_url(candidate)
                    if not normalized or ignored_url(normalized) or not same_host(normalized, host):
                        continue
                    if normalized not in seen_queue and normalized not in seen_seeds:
                        seed_queue.append(normalized)
                        seen_queue.add(normalized)
                        discovered_urls.add(normalized)

                if len(all_records) % PROGRESS_EVERY == 0 or len(all_records) == 1:
                    write_progress(
                        SNAPSHOT_DIR,
                        {
                            'provider_id': PROVIDER_ID,
                            'generated_at': datetime.now(timezone.utc).isoformat(),
                            'seed_pages_seen': len(seen_seeds),
                            'queue_size': len(seed_queue),
                            'records': len(all_records),
                            'discovered_urls': len(discovered_urls),
                            'last_seed': seed_url,
                        },
                    )
        finally:
            try:
                context.close()
            finally:
                if browser is not None:
                    browser.close()

    deduped = dedupe_records(all_records, EXCLUDE_KEYWORDS)
    coverage['discovered_seed_count'] = len(seen_seeds)
    coverage['discovered_record_count'] = len(all_records)
    coverage['discovered_url_count'] = len(discovered_urls)
    coverage['deduped_record_count'] = len(deduped)
    notes.append(f'Seed pages crawled: {len(seen_seeds)}')
    notes.append(f'Records before dedupe: {len(all_records)}')
    notes.append(f'Records after dedupe: {len(deduped)}')
    notes.append(MANUAL_NOTE)
    return deduped, list(dict.fromkeys(notes)), coverage


def run_extractor(snapshot_date: str | None = None) -> Path:
    global SNAPSHOT_DATE, SNAPSHOT_DIR
    if snapshot_date:
        SNAPSHOT_DATE = snapshot_date
        SNAPSHOT_DIR = BASE_DIR / 'snapshots' / SNAPSHOT_DATE
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / 'provider.json'
    if not metadata_path.exists():
        raise SystemExit(f'Missing provider metadata: {metadata_path}')
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    products, notes, coverage = crawl_provider(metadata, seed_snapshot)
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=products,
        notes=notes,
        snapshot_date=SNAPSHOT_DATE,
    )
    payload['catalog_coverage'] = coverage
    return write_snapshot_bundle(output_root=output_root, snapshot_date=SNAPSHOT_DATE, payload=payload, products=products)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f'Live catalog extractor for {PROVIDER_ID}.')
    parser.add_argument('--snapshot-date', default=None)
    args = parser.parse_args(argv)
    path = run_extractor(snapshot_date=args.snapshot_date)
    print(json.dumps({'provider_id': PROVIDER_ID, 'snapshot_path': str(path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())






