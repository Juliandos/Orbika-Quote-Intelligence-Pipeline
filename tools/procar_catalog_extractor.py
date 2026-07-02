#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import urlparse

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
    decode_html,
    dedupe_records,
    default_category_like_url,
    default_product_like_url,
    entry_urls_from_snapshot,
    extract_links,
    extract_meta_content,
    extract_page_title,
    fetch_url,
    guess_page_number,
    ignored_by_keywords,
    iter_json_ld_nodes,
    latest_snapshot_json,
    load_json,
    parse_category_record,
    parse_json_ld_blocks,
    parse_pdf_records,
    parse_product_fallback,
    product_from_json_ld,
    provider_paths,
    same_host,
    normalize_text,
    url_matches_any,
    write_snapshot_bundle,
)

CONFIG = {
    'provider_id': 'procar',
    'display_name': 'Procar',
    'max_pages': 5000,
    'max_products': 10000,
    'category_only_mode': False,
    'prefer_vehicle_match': True,
    'collect_pdf_links': False,
    'image_catalog_only': False,
    'static_entry_urls': (
        'https://procar.com.co/categoria-producto/llantas/',
        'https://procar.com.co/categoria-producto/llantas/auto/',
        'https://procar.com.co/categoria-producto/llantas/camioneta/',
        'https://procar.com.co/categoria-producto/filtros/',
        'https://procar.com.co/categoria-producto/lubricantes/',
        'https://procar.com.co/categoria-producto/otros-productos/',
    ),
    'allow_category_records': False,
    'extra_product_patterns': ('/producto/',),
    'extra_category_patterns': ('/categoria-producto/',),
    'disallowed_url_patterns': (),
}
EXCLUDE_KEYWORDS = ('moto', 'motoc', 'camion', 'camiones', 'bus', 'buses', 'tracto', 'npr', 'diesel', 'agricola', 'industrial')
VEHICLE_TOKENS = ('chevrolet', 'mazda', 'renault', 'kia', 'hyundai', 'nissan', 'toyota', 'ford', 'volkswagen')

PROVIDER_ID = CONFIG['provider_id']
DISPLAY_NAME = CONFIG['display_name']
MAX_PAGES = CONFIG['max_pages']
MAX_PRODUCTS = CONFIG['max_products']
CATEGORY_ONLY_MODE = CONFIG['category_only_mode']
PREFER_VEHICLE_MATCH = CONFIG['prefer_vehicle_match']
COLLECT_PDF_LINKS = CONFIG['collect_pdf_links']
IMAGE_CATALOG_ONLY = CONFIG['image_catalog_only']
ALLOW_CATEGORY_RECORDS = CONFIG['allow_category_records']
STATIC_ENTRY_URLS = CONFIG['static_entry_urls']
EXTRA_PRODUCT_PATTERNS = CONFIG['extra_product_patterns']
EXTRA_CATEGORY_PATTERNS = CONFIG['extra_category_patterns']
DISALLOWED_URL_PATTERNS = CONFIG['disallowed_url_patterns']


def infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = ' '.join(filter(None, [title, category_name, description])).lower()
    if CATEGORY_ONLY_MODE:
        return 'category_only', 'medium', True
    if PREFER_VEHICLE_MATCH and any(token in allowed_text for token in VEHICLE_TOKENS):
        return 'vehicle_compatible', 'medium', True
    if reference and not CATEGORY_ONLY_MODE:
        return ('vehicle_compatible' if PREFER_VEHICLE_MATCH else 'category_only'), 'medium', True
    return 'category_only', 'medium', True


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    if 'camioneta' in lowered:
        return False
    return url_matches_any(url, DISALLOWED_URL_PATTERNS) or ignored_by_keywords(url, EXCLUDE_KEYWORDS)


def product_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    return default_product_like_url(url) or url_matches_any(url, EXTRA_PRODUCT_PATTERNS)


def category_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    return default_category_like_url(url) or url_matches_any(url, EXTRA_CATEGORY_PATTERNS)


def metadata_entry_urls(metadata: dict[str, object]) -> list[str]:
    entry_urls: list[str] = []
    catalog = metadata.get('catalog')
    if isinstance(catalog, dict):
        for value in catalog.get('entry_urls', []) or []:
            if isinstance(value, str) and value.startswith('http'):
                entry_urls.append(value)
    selectors = metadata.get('selectors')
    if isinstance(selectors, dict):
        for value in selectors.get('category_entry_urls', []) or []:
            if isinstance(value, str) and value.startswith('http'):
                entry_urls.append(value)
    return entry_urls


def strip_tags(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r'<[^>]+>', ' ', value)
    text = normalize_text(text)
    return text or None


def extract_procar_description(html: str) -> str | None:
    patterns = [
        r'<div[^>]+id="tab-description"[^>]*>(.*?)<div[^>]+id="tab-reviews"',
        r'<div[^>]+class="woocommerce-Tabs-panel[^\"]*--description[^\"]*"[^>]*>(.*?)<div[^>]+class="woocommerce-Tabs-panel[^\"]*--reviews',
        r'<div[^>]+class="woocommerce-product-details__short-description"[^>]*>(.*?)</div>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            text = strip_tags(match.group(1))
            if text:
                text = re.sub(r'^Description\s*', '', text, flags=re.IGNORECASE)
                return text
    return extract_meta_content(html, 'description')


def extract_procar_product_meta(html: str) -> tuple[str | None, str | None, str | None]:
    category_name = None
    subcategory_name = None
    brand = None

    category_match = re.search(
        r'<span class="posted_in detail-container">.*?<span class="detail-content">(.*?)</span></span>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if category_match:
        anchors = re.findall(r'>([^<]+)</a>', category_match.group(1), re.IGNORECASE | re.DOTALL)
        cleaned = [normalize_text(anchor) for anchor in anchors if normalize_text(anchor)]
        if cleaned:
            if len(cleaned) >= 2:
                category_name, subcategory_name = cleaned[-1], cleaned[0]
            else:
                category_name = cleaned[0]

    brand_match = re.search(
        r'<span class="posted_in">Marca:\s*<a[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if brand_match:
        brand = normalize_text(brand_match.group(1))

    return category_name, subcategory_name, brand


def extract_procar_reference(html: str) -> str | None:
    candidates = [
        r'\bN[ºo]\s*de\s*parte[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./]+)',
        r'\bReferencia[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./]+)',
        r'\bSKU[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\-\./]+)',
    ]
    for pattern in candidates:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = normalize_text(match.group(1))
            if value:
                return value
    return None


def build_procar_record(
    *,
    url: str,
    html: str,
    source_page_url: str,
    infer_match_type: Callable[[str | None, str | None, str | None, str | None], tuple[str, str, bool]],
) -> ProductRecord | None:
    title = extract_page_title(html)
    if not title:
        return None
    category_name, subcategory_name, brand = extract_procar_product_meta(html)
    description = extract_procar_description(html)
    image_url = extract_meta_content(html, 'og:image')
    reference = extract_procar_reference(html)
    sku = reference
    vehicle_scope = None
    lowered_text = ' '.join(filter(None, [title, category_name, subcategory_name, description, brand])).lower()
    if any(token in lowered_text for token in ('auto', 'automotriz', 'vehiculo', 'vehículo', 'camioneta')):
        vehicle_scope = 'Autos'
    match_type, confidence, manual = infer_match_type(title, category_name, description, reference)
    return ProductRecord(
        item_type='product',
        provider_type='product_catalog',
        product_name=title,
        product_url=url,
        detail_url=url,
        category_name=category_name,
        subcategory_name=subcategory_name,
        brand=brand,
        reference=reference,
        sku=sku,
        supplier_item_code=sku,
        description=description,
        vehicle_scope=vehicle_scope,
        image_url=image_url,
        source_page_url=source_page_url,
        page_number=guess_page_number(source_page_url),
        match_type=match_type,
        match_confidence=confidence,
        requires_manual_confirmation=manual,
        searchable_tokens=build_searchable_tokens(
            title,
            brand,
            category_name,
            subcategory_name,
            description,
            reference,
            sku,
            vehicle_scope,
        ),
    )


def enrich_product_record(record: ProductRecord, html: str) -> ProductRecord:
    title = record.product_name or record.title
    category_name, subcategory_name, brand = extract_procar_product_meta(html)
    description = extract_procar_description(html) or record.description
    image_url = extract_meta_content(html, 'og:image') or record.image_url
    reference = extract_procar_reference(html) or record.reference
    sku = reference or record.sku
    vehicle_scope = record.vehicle_scope
    lowered_text = ' '.join(filter(None, [title, category_name, subcategory_name, description, brand])).lower()
    if not vehicle_scope and any(token in lowered_text for token in ('auto', 'automotriz', 'vehiculo', 'vehículo', 'camioneta')):
        vehicle_scope = 'Autos'
    searchable_tokens = build_searchable_tokens(
        title,
        brand or record.brand,
        category_name or record.category_name,
        subcategory_name or record.subcategory_name,
        description,
        reference,
        sku,
        vehicle_scope,
    )
    return replace(
        record,
        category_name=category_name or record.category_name,
        subcategory_name=subcategory_name or record.subcategory_name,
        brand=brand or record.brand,
        reference=reference,
        sku=sku,
        supplier_item_code=sku,
        description=description,
        vehicle_scope=vehicle_scope,
        image_url=image_url,
        searchable_tokens=searchable_tokens,
    )


def crawl_provider(metadata: dict[str, object], seed_snapshot: dict[str, object] | None) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get('website') or metadata.get('catalog_root_url') or '')).netloc.lower()
    entry_urls = [str(metadata.get('catalog_root_url') or metadata.get('website') or '')]
    entry_urls.extend(STATIC_ENTRY_URLS)
    entry_urls.extend(metadata_entry_urls(metadata))
    if seed_snapshot:
        entry_urls.extend(entry_urls_from_snapshot(seed_snapshot))

    queue: list[tuple[str, str]] = []
    seen_queue: set[str] = set()
    for url in entry_urls:
        if not url or not url.startswith('http'):
            continue
        normalized = canonical_url(url)
        if ignored_url(normalized):
            continue
        if normalized not in seen_queue and same_host(normalized, host):
            queue.append((normalized, normalized))
            seen_queue.add(normalized)

    visited: set[str] = set()
    records: list[ProductRecord] = []
    notes = [AUTOS_ONLY_NOTE]

    while queue and len(visited) < MAX_PAGES and len(records) < MAX_PRODUCTS:
        url, source_page_url = queue.pop(0)
        if url in visited or ignored_url(url):
            continue
        visited.add(url)
        try:
            final_url, raw, headers = fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f'Fetch warning for {url}: {exc}')
            continue

        if ignored_url(final_url):
            continue

        content_type = headers.get('content-type', '').lower()
        if 'pdf' in content_type or final_url.lower().endswith('.pdf'):
            if COLLECT_PDF_LINKS:
                records.extend(parse_pdf_records(f'<a href="{final_url}">{DISPLAY_NAME}</a>', final_url, source_page_url))
            continue

        html = decode_html(raw, headers)
        if COLLECT_PDF_LINKS:
            records.extend(parse_pdf_records(html, final_url, source_page_url))

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

        is_product_page = bool(product_records) or product_like_url(final_url)
        if is_product_page and product_records:
            product_records = [enrich_product_record(record, html) for record in product_records]
        if is_product_page and not product_records:
            fallback = build_procar_record(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                infer_match_type=infer_match_type,
            )
            if not fallback:
                fallback = parse_product_fallback(
                    url=final_url,
                    html=html,
                    source_page_url=source_page_url,
                    category_only_mode=CATEGORY_ONLY_MODE,
                    infer_match_type=infer_match_type,
                )
            if fallback:
                product_records = [fallback]

        if product_records:
            records.extend(product_records)
        elif ALLOW_CATEGORY_RECORDS and (category_like_url(final_url) or final_url in entry_urls):
            category_record = parse_category_record(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                exclude_keywords=EXCLUDE_KEYWORDS,
                match_type='category_only' if CATEGORY_ONLY_MODE else 'manual_confirmation_required',
            )
            if category_record:
                records.append(category_record)

        for link in extract_links(html, final_url):
            if link in visited or link in seen_queue:
                continue
            if not same_host(link, host) or ignored_url(link):
                continue
            if COLLECT_PDF_LINKS and link.lower().endswith('.pdf'):
                queue.append((link, final_url))
                seen_queue.add(link)
                continue
            if product_like_url(link) or category_like_url(link):
                queue.append((link, final_url))
                seen_queue.add(link)

    if IMAGE_CATALOG_ONLY and not records and entry_urls:
        records.append(
            ProductRecord(
                item_type='category',
                provider_type='category_only',
                title=DISPLAY_NAME,
                detail_url=entry_urls[0],
                category_name=DISPLAY_NAME,
                description='Catalogo visual publico; la extraccion viva se mantiene como verificacion manual.',
                source_page_url=entry_urls[0],
                match_type='manual_confirmation_required',
                match_confidence='low',
                requires_manual_confirmation=True,
                searchable_tokens=[DISPLAY_NAME.lower(), 'catalogo', 'visual'],
            )
        )

    return dedupe_records(records, EXCLUDE_KEYWORDS), list(dict.fromkeys(notes + [MANUAL_NOTE]))


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / 'provider.json'
    if not metadata_path.exists():
        raise SystemExit(f'Missing provider metadata: {metadata_path}')
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes = crawl_provider(metadata, seed_snapshot)
    payload = build_payload(
        provider_id=PROVIDER_ID,
        provider_name=DISPLAY_NAME,
        metadata=metadata,
        products=products,
        notes=notes,
        snapshot_date=snapshot_day,
    )
    return write_snapshot_bundle(output_root=output_root, snapshot_date=snapshot_day, payload=payload, products=products)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f'Live catalog extractor for {PROVIDER_ID}.')
    parser.add_argument('--snapshot-date', default=None)
    args = parser.parse_args(argv)
    path = run_extractor(snapshot_date=args.snapshot_date)
    print(json.dumps({'provider_id': PROVIDER_ID, 'snapshot_path': str(path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
