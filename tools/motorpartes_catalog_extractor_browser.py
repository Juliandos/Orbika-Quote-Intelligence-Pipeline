#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.motorpartes_browser_probe import (  # noqa: E402
    CATEGORY_URLS,
    collect_product_links_on_page,
    current_page_number,
    detect_browser_executable,
    discover_numeric_pages,
    get_playwright,
    go_to_next_page,
    go_to_numeric_page,
    settle_category_view,
)
from tools.seeded_catalog_support import (  # noqa: E402
    AUTOS_ONLY_NOTE,
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
    canonical_url,
    decode_html,
    dedupe_records,
    extract_meta_content,
    extract_page_title,
    fetch_url,
    ignored_by_keywords,
    iter_json_ld_nodes,
    latest_snapshot_json,
    load_json,
    parse_json_ld_blocks,
    parse_product_fallback,
    product_from_json_ld,
    provider_paths,
    write_snapshot_bundle,
)

PROVIDER_ID = 'motorpartes'
DISPLAY_NAME = 'Motorpartes'
EXCLUDE_KEYWORDS = ('motoc', 'camion', 'camiones', 'bus', 'buses', 'tracto', 'npr', 'diesel', 'agricola', 'industrial')
VEHICLE_TOKENS = ('chevrolet', 'mazda', 'renault', 'kia', 'hyundai', 'nissan', 'toyota', 'ford', 'volkswagen')
MAX_PRODUCTS = 50000


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, '').strip().lower()
    if not raw:
        return default
    return raw in {'1', 'true', 'yes', 'on'}


def infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = ' '.join(filter(None, [title, category_name, description])).lower()
    if any(token in allowed_text for token in VEHICLE_TOKENS):
        return 'vehicle_compatible', 'medium', True
    if reference:
        return 'vehicle_compatible', 'medium', True
    return 'category_only', 'medium', True


def log_progress(event: str, **payload: object) -> None:
    print(json.dumps({'event': event, **payload}, ensure_ascii=False), flush=True)


def ignored_url(url: str) -> bool:
    parsed = urlparse(url)
    text = ' '.join(filter(None, [parsed.path, parsed.query]))
    return ignored_by_keywords(text, EXCLUDE_KEYWORDS)


def crawl_listing_urls(notes: list[str]) -> tuple[dict[str, str], dict[str, Any]]:
    sync_playwright = get_playwright()
    browser_path = detect_browser_executable()
    product_sources: dict[str, str] = {}
    diagnostics: dict[str, Any] = {
        'category_stats': [],
        'discovered_product_urls': [],
        'listing_url_count': 0,
    }
    headed = bool_env('MOTORPARTES_HEADED', False)
    slow_mo = int(os.environ.get('MOTORPARTES_SLOW_MO', '40') or '40')
    with sync_playwright() as playwright:
        launch_kwargs = {'headless': not headed, 'slow_mo': slow_mo}
        if browser_path:
            launch_kwargs['executable_path'] = browser_path
        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={'width': 1440, 'height': 960})
        page = context.new_page()
        for category_url in CATEGORY_URLS:
            category_stats: dict[str, Any] = {
                'category_url': category_url,
                'visited_pages': [],
                'pages_visited_count': 0,
                'new_urls_discovered': 0,
            }
            try:
                page.goto(category_url, wait_until='domcontentloaded', timeout=45000)
                page.wait_for_timeout(1800)
            except Exception as exc:  # noqa: BLE001
                notes.append(f'No se pudo abrir {category_url}: {exc}')
                category_stats['error'] = str(exc)
                diagnostics['category_stats'].append(category_stats)
                continue
            visited_pages: set[int] = set()
            log_progress('motorpartes_category_started', category_url=category_url)
            while True:
                settle_category_view(page, 3, 1800)
                current = current_page_number(page)
                visited_pages.add(current)
                if current not in category_stats['visited_pages']:
                    category_stats['visited_pages'].append(current)
                for product_url in collect_product_links_on_page(page):
                    if product_url not in product_sources:
                        product_sources[product_url] = canonical_url(page.url)
                        category_stats['new_urls_discovered'] += 1
                        diagnostics['discovered_product_urls'].append(
                            {
                                'product_url': product_url,
                                'source_page_url': canonical_url(page.url),
                            }
                        )
                    if len(product_sources) >= MAX_PRODUCTS:
                        notes.append(f'Se alcanzó el límite de productos configurado ({MAX_PRODUCTS}).')
                        category_stats['pages_visited_count'] = len(visited_pages)
                        diagnostics['category_stats'].append(category_stats)
                        diagnostics['listing_url_count'] = len(product_sources)
                        log_progress('motorpartes_listing_limit_reached', listing_url_count=len(product_sources))
                        context.close()
                        browser.close()
                        return product_sources, diagnostics
                discovered_pages = [n for n in discover_numeric_pages(page) if n not in visited_pages and n > current]
                moved = False
                for page_number in discovered_pages:
                    if go_to_numeric_page(page, page_number):
                        moved = True
                        break
                if moved:
                    continue
                if go_to_next_page(page):
                    continue
                break
            category_stats['pages_visited_count'] = len(visited_pages)
            diagnostics['category_stats'].append(category_stats)
            log_progress(
                'motorpartes_category_completed',
                category_url=category_url,
                pages_visited=category_stats['pages_visited_count'],
                category_new_urls=category_stats['new_urls_discovered'],
                listing_url_count=len(product_sources),
            )
        context.close()
        browser.close()
    diagnostics['listing_url_count'] = len(product_sources)
    return product_sources, diagnostics


def parse_product_detail(product_url: str, source_page_url: str, notes: list[str]) -> ProductRecord | None:
    try:
        final_url, raw, headers = fetch_url(product_url)
    except Exception as exc:  # noqa: BLE001
        notes.append(f'Fetch warning for {product_url}: {exc}')
        return None
    if ignored_url(final_url):
        return None
    html = decode_html(raw, headers)
    page_title = extract_page_title(html)
    meta_description = extract_meta_content(html, 'description')
    meta_image = extract_meta_content(html, 'og:image')
    json_ld_nodes = [node for block in parse_json_ld_blocks(html) for node in iter_json_ld_nodes(block)]
    product_records = product_from_json_ld(
        url=final_url,
        page_title=page_title,
        description=meta_description,
        image_url=meta_image,
        source_page_url=source_page_url,
        json_ld_nodes=json_ld_nodes,
        infer_match_type=infer_match_type,
    )
    if product_records:
        return product_records[0]
    return parse_product_fallback(
        url=final_url,
        html=html,
        source_page_url=source_page_url,
        category_only_mode=False,
        infer_match_type=infer_match_type,
    )


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str], dict[str, Any]]:
    notes = [AUTOS_ONLY_NOTE]
    product_sources, diagnostics = crawl_listing_urls(notes)
    diagnostics['seed_urls_added'] = 0
    if seed_snapshot:
        for entry in seed_snapshot.get('products', []):
            if not isinstance(entry, dict):
                continue
            url = entry.get('product_url') or entry.get('detail_url')
            source_page_url = entry.get('source_page_url') or metadata.get('catalog_root_url') or metadata.get('website')
            if isinstance(url, str) and url.startswith('http') and '/producto/' in url.lower():
                normalized = canonical_url(url)
                if normalized not in product_sources:
                    product_sources[normalized] = str(source_page_url)
                    diagnostics['seed_urls_added'] += 1
    notes.append(
        f'Se descubrieron {len(product_sources)} URLs de detalle antes del parseo '
        f'({diagnostics["seed_urls_added"]} agregadas desde snapshot previo).'
    )
    records: list[ProductRecord] = []
    parse_failures: list[dict[str, str]] = []
    parse_attempted = 0
    parse_succeeded = 0
    for index, (url, source) in enumerate(product_sources.items(), start=1):
        parse_attempted += 1
        record = parse_product_detail(url, source, notes)
        if record is None:
            if len(parse_failures) < 100:
                parse_failures.append({'product_url': url, 'source_page_url': source})
            continue
        records.append(record)
        parse_succeeded += 1
        if index == 1 or index % 50 == 0:
            log_progress(
                'motorpartes_parse_progress',
                attempted=parse_attempted,
                parsed=parse_succeeded,
                failed=parse_attempted - parse_succeeded,
            )
    deduped = dedupe_records(records, ())
    diagnostics['parse_attempted'] = parse_attempted
    diagnostics['parse_succeeded'] = parse_succeeded
    diagnostics['parse_failed'] = parse_attempted - parse_succeeded
    diagnostics['parse_failures_sample'] = parse_failures
    diagnostics['deduped_product_count'] = len(deduped)
    notes.append(
        f'Parseo de detalle: {parse_succeeded}/{parse_attempted} productos convertidos '
        f'y {len(deduped)} después de deduplicación.'
    )
    return deduped, list(dict.fromkeys(notes + [MANUAL_NOTE])), diagnostics


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / 'provider.json'
    if not metadata_path.exists():
        raise SystemExit(f'Missing provider metadata: {metadata_path}')
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes, diagnostics = crawl_provider(metadata, seed_snapshot)
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=products,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    payload['diagnostics'] = diagnostics
    extracted_path = write_snapshot_bundle(output_root=output_root, snapshot_date=snapshot_day, payload=payload, products=products)
    diagnostics_path = extracted_path.parent / 'intermediate_diagnostics.json'
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding='utf-8')
    log_progress(
        'motorpartes_extractor_completed',
        snapshot_path=str(extracted_path),
        products=len(products),
        listing_url_count=diagnostics.get('listing_url_count', 0),
        parse_succeeded=diagnostics.get('parse_succeeded', 0),
    )
    return extracted_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f'Browser catalog extractor for {PROVIDER_ID}.')
    parser.add_argument('--snapshot-date', default=None)
    args = parser.parse_args(argv)
    path = run_extractor(snapshot_date=args.snapshot_date)
    print(json.dumps({'provider_id': PROVIDER_ID, 'snapshot_path': str(path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
