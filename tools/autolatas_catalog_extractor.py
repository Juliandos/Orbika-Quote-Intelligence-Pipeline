#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
import sys
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.seeded_catalog_support import (
    AUTOS_ONLY_NOTE,
    MANUAL_NOTE,
    ProductRecord,
    build_payload,
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
    ignored_by_keywords,
    iter_json_ld_nodes,
    latest_snapshot_json,
    load_json,
    parse_category_record,
    parse_json_ld_blocks,
    parse_pdf_records,
    parse_product_fallback,
    guess_page_number,
    product_from_json_ld,
    provider_paths,
    build_searchable_tokens,
    same_host,
    slug_to_words,
    url_matches_any,
    write_snapshot_bundle,
)

CONFIG = {'provider_id': 'autolatas', 'display_name': 'Autolatas', 'max_pages': 1000, 'max_products': 5000, 'category_only_mode': False, 'prefer_vehicle_match': True, 'collect_pdf_links': False, 'image_catalog_only': False, 'static_entry_urls': (), 'allow_category_records': False, 'extra_product_patterns': ('/ampliacion/',), 'extra_category_patterns': (), 'disallowed_url_patterns': ()}
EXCLUDE_KEYWORDS = ('moto', 'motoc', 'camion', 'camiones', 'bus', 'buses', 'tracto', 'npr', 'diesel', 'agricola', 'industrial')
VEHICLE_TOKENS = ('chevrolet', 'mazda', 'renault', 'kia', 'hyundai', 'nissan', 'toyota', 'ford', 'volkswagen')

PROVIDER_ID = CONFIG["provider_id"]
DISPLAY_NAME = CONFIG["display_name"]
MAX_PAGES = CONFIG["max_pages"]
MAX_PRODUCTS = CONFIG["max_products"]
CATEGORY_ONLY_MODE = CONFIG["category_only_mode"]
PREFER_VEHICLE_MATCH = CONFIG["prefer_vehicle_match"]
COLLECT_PDF_LINKS = CONFIG["collect_pdf_links"]
IMAGE_CATALOG_ONLY = CONFIG["image_catalog_only"]
ALLOW_CATEGORY_RECORDS = CONFIG["allow_category_records"]
STATIC_ENTRY_URLS = CONFIG["static_entry_urls"]
EXTRA_PRODUCT_PATTERNS = CONFIG["extra_product_patterns"]
EXTRA_CATEGORY_PATTERNS = CONFIG["extra_category_patterns"]
DISALLOWED_URL_PATTERNS = CONFIG["disallowed_url_patterns"]
LISTING_SUMMARY_RE = re.compile(
    r"(?:Showing|Mostrando)\s+(\d+)\s*[–-]\s*(\d+)\s+(?:of|de)\s+(\d+)\s+(?:results|resultados)",
    re.I,
)


def build_listing_page_url(page_url: str, page_number: int) -> str:
    parsed = urlparse(page_url)
    path = parsed.path or "/"
    if "/page/" in path:
        base_path = re.sub(r"/page/\d+/?$", "/", path)
    else:
        base_path = path if path.endswith("/") else f"{path}/"
    if page_number <= 1:
        new_path = base_path
    else:
        new_path = f"{base_path.rstrip('/')}/page/{page_number}/"
    return parsed._replace(path=new_path, query="").geturl()


def browser_render_links(page_url: str) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.goto(page_url, wait_until="networkidle", timeout=120000)
            page.wait_for_timeout(2000)
            hrefs = page.eval_on_selector_all("a[href]", "els => els.map(a => a.href)")
            browser.close()
            return [str(href) for href in hrefs if href]
    except Exception:
        return []


def infer_match_type(title: str | None, category_name: str | None, description: str | None, reference: str | None) -> tuple[str, str, bool]:
    allowed_text = " ".join(filter(None, [title, category_name, description])).lower()
    if CATEGORY_ONLY_MODE:
        return "category_only", "medium", True
    if PREFER_VEHICLE_MATCH and any(token in allowed_text for token in VEHICLE_TOKENS):
        return "vehicle_compatible", "medium", True
    if reference and not CATEGORY_ONLY_MODE:
        return ("vehicle_compatible" if PREFER_VEHICLE_MATCH else "category_only"), "medium", True
    return "category_only", "medium", True


def ignored_url(url: str) -> bool:
    lowered = url.lower()
    if "add-to-cart=" in lowered or "/wp-json/" in lowered or "/xmlrpc.php" in lowered:
        return True
    return url_matches_any(url, DISALLOWED_URL_PATTERNS) or ignored_by_keywords(url, EXCLUDE_KEYWORDS)


def product_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    normalized = canonical_url(url)
    lowered = normalized.lower()
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    if path == "/ampliacion":
        return False
    if "/ampliacion/" in lowered and "?" not in lowered and not lowered.rstrip("/").endswith("/ampliacion"):
        return True
    if default_product_like_url(normalized):
        return not category_like_url(normalized) and "?" not in lowered
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 2 and "/page/" not in lowered and not category_like_url(normalized):
        if not segments[-1].isdigit() and segments[-1] not in {"feed", "page"}:
            return True
    return False


def category_like_url(url: str) -> bool:
    if ignored_url(url):
        return False
    return default_category_like_url(url) or url_matches_any(url, EXTRA_CATEGORY_PATTERNS)


def crawl_provider(
    metadata: dict[str, object],
    seed_snapshot: dict[str, object] | None,
    output_root: Path | None = None,
    snapshot_day: str | None = None,
) -> tuple[list[ProductRecord], list[str]]:
    host = urlparse(str(metadata.get("website") or metadata.get("catalog_root_url") or "")).netloc.lower()
    entry_urls = [str(metadata.get("catalog_root_url") or metadata.get("website") or "")]
    entry_urls.extend(STATIC_ENTRY_URLS)
    if seed_snapshot:
        entry_urls.extend(entry_urls_from_snapshot(seed_snapshot))

    queue: list[tuple[str, str]] = []
    seen_queue: set[str] = set()
    for url in entry_urls:
        if not url or not url.startswith("http"):
            continue
        normalized = canonical_url(url)
        if ignored_url(normalized):
            continue
        if normalized not in seen_queue and same_host(normalized, host):
            queue.append((normalized, normalized))
            seen_queue.add(normalized)

    visited_listing_pages: set[str] = set()
    discovered_product_sources: dict[str, str] = {}
    notes = [AUTOS_ONLY_NOTE]
    root_listing_url = canonical_url(str(metadata.get("catalog_root_url") or metadata.get("website") or ""))
    last_progress_snapshot = 0

    def discovery_records() -> list[ProductRecord]:
        records: list[ProductRecord] = []
        for product_url, source_page_url in discovered_product_sources.items():
            slug = Path(urlparse(product_url).path).stem or Path(urlparse(product_url).path).name
            title = slug_to_words(slug) or DISPLAY_NAME
            records.append(
                ProductRecord(
                    item_type="product",
                    provider_type="category_only",
                    title=title,
                    product_name=title,
                    detail_url=product_url,
                    product_url=product_url,
                    category_name=slug_to_words(Path(urlparse(source_page_url).path).stem) or "Catalogo publico",
                    description="Producto descubierto desde el catalogo publico; pendiente de enriquecimiento detallado.",
                    source_page_url=source_page_url,
                    page_number=1,
                    match_type="manual_confirmation_required",
                    match_confidence="low",
                    requires_manual_confirmation=True,
                    searchable_tokens=build_searchable_tokens(DISPLAY_NAME, title, slug, "catalogo", "publico"),
                )
            )
        return dedupe_records(records, EXCLUDE_KEYWORDS)

    def persist_snapshot(reason: str, products: list[ProductRecord]) -> None:
        if output_root is None or snapshot_day is None or not products:
            return
        payload = build_payload(
            provider_id=PROVIDER_ID,
            provider_name=DISPLAY_NAME,
            metadata=metadata,
            products=dedupe_records(products, EXCLUDE_KEYWORDS),
            notes=list(dict.fromkeys(notes + [f"Progress snapshot: {reason}"])),
            snapshot_date=snapshot_day,
        )
        write_snapshot_bundle(output_root=output_root, snapshot_date=snapshot_day, payload=payload, products=dedupe_records(products, EXCLUDE_KEYWORDS))

    while queue and len(visited_listing_pages) < MAX_PAGES:
        url, source_page_url = queue.pop(0)
        if url in visited_listing_pages or ignored_url(url):
            continue
        visited_listing_pages.add(url)
        try:
            final_url, raw, headers = fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Fetch warning for {url}: {exc}")
            continue

        if ignored_url(final_url):
            continue

        content_type = headers.get("content-type", "").lower()
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            continue

        html = decode_html(raw, headers)
        text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
        text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        summary_match = LISTING_SUMMARY_RE.search(text)
        browser_links: list[str] = []
        if guess_page_number(final_url) <= 2 or final_url.rstrip("/").endswith("/tienda"):
            browser_links = browser_render_links(final_url)
        links = list(dict.fromkeys(extract_links(html, final_url) + browser_links))
        if summary_match:
            start, end, total = (int(summary_match.group(1)), int(summary_match.group(2)), int(summary_match.group(3)))
            per_page = max(1, end - start + 1)
            total_pages = max(1, math.ceil(total / per_page))
            for page_number in range(1, total_pages + 1):
                listing_url = build_listing_page_url(final_url, page_number)
                if listing_url not in visited_listing_pages and listing_url not in seen_queue and same_host(listing_url, host):
                    queue.append((listing_url, final_url))
                    seen_queue.add(listing_url)

        if COLLECT_PDF_LINKS:
            for link in links:
                if same_host(link, host) and link.lower().endswith(".pdf"):
                    queue.append((link, final_url))
                    seen_queue.add(link)

        for link in links:
            if link in visited_listing_pages or link in seen_queue:
                continue
            if not same_host(link, host) or ignored_url(link):
                continue
            if product_like_url(link):
                discovered_product_sources.setdefault(canonical_url(link), final_url)
                continue
            if category_like_url(link):
                queue.append((link, final_url))
                seen_queue.add(link)

        if len(discovered_product_sources) and (len(discovered_product_sources) - last_progress_snapshot >= 25 or len(visited_listing_pages) == 1):
            persist_snapshot(f"discovery {len(discovered_product_sources)}", discovery_records())
            last_progress_snapshot = len(discovered_product_sources)

    discovery_bundle = discovery_records()
    persist_snapshot("discovery complete", discovery_bundle)

    def parse_product_detail(product_url: str, source_page_url: str) -> tuple[list[ProductRecord], str | None]:
        try:
            final_url, raw, headers = fetch_url(product_url)
        except Exception as exc:  # noqa: BLE001
            return [], f"Fetch warning for {product_url}: {exc}"

        if ignored_url(final_url):
            return [], None

        content_type = headers.get("content-type", "").lower()
        if "pdf" in content_type or final_url.lower().endswith(".pdf"):
            if COLLECT_PDF_LINKS:
                return parse_pdf_records(f'<a href="{final_url}">{DISPLAY_NAME}</a>', final_url, source_page_url), None
            return [], None

        html = decode_html(raw, headers)
        page_title = extract_page_title(html)
        meta_description = extract_meta_content(html, "description")
        meta_image = extract_meta_content(html, "og:image")
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
        if not product_records:
            fallback = parse_product_fallback(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                category_only_mode=CATEGORY_ONLY_MODE,
                infer_match_type=infer_match_type,
            )
            if fallback:
                product_records = [fallback]
        if not product_records and ALLOW_CATEGORY_RECORDS and (category_like_url(final_url) or final_url in entry_urls):
            category_record = parse_category_record(
                url=final_url,
                html=html,
                source_page_url=source_page_url,
                exclude_keywords=EXCLUDE_KEYWORDS,
                match_type="category_only" if CATEGORY_ONLY_MODE else "manual_confirmation_required",
            )
            if category_record:
                product_records = [category_record]
        return product_records, None

    parsed_records: list[ProductRecord] = []
    workers = min(16, max(1, len(discovered_product_sources)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(parse_product_detail, product_url, source_url): product_url for product_url, source_url in discovered_product_sources.items()}
        for index, future in enumerate(as_completed(future_map), start=1):
            product_records, warning = future.result()
            if warning:
                notes.append(warning)
            if product_records:
                parsed_records.extend(product_records)
            if index == 1 or index % 50 == 0 or index == len(future_map):
                persist_snapshot(f"parsed {index}", dedupe_records(parsed_records + discovery_bundle, EXCLUDE_KEYWORDS))

    final_records = dedupe_records(parsed_records + discovery_bundle, EXCLUDE_KEYWORDS)
    if IMAGE_CATALOG_ONLY and not final_records and entry_urls:
        final_records.append(
            ProductRecord(
                item_type="category",
                provider_type="category_only",
                title=DISPLAY_NAME,
                detail_url=entry_urls[0],
                category_name=DISPLAY_NAME,
                description="Catalogo visual publico; la extraccion viva se mantiene como verificacion manual.",
                source_page_url=entry_urls[0],
                match_type="manual_confirmation_required",
                match_confidence="low",
                requires_manual_confirmation=True,
                searchable_tokens=[DISPLAY_NAME.lower(), "catalogo", "visual"],
            )
        )

    notes = list(dict.fromkeys(notes + [MANUAL_NOTE, f"Listing pages crawled: {len(visited_listing_pages)}", f"Product pages discovered: {len(discovered_product_sources)}"]))
    return final_records, notes


def run_extractor(snapshot_date: str | None = None) -> Path:
    provider_dir, output_root = provider_paths(PROVIDER_ID)
    metadata_path = provider_dir / "provider.json"
    if not metadata_path.exists():
        raise SystemExit(f"Missing provider metadata: {metadata_path}")
    metadata = load_json(metadata_path)
    previous_path = latest_snapshot_json(PROVIDER_ID)
    seed_snapshot = load_json(previous_path) if previous_path and previous_path.exists() else None
    snapshot_day = snapshot_date or date.today().isoformat()
    products, notes = crawl_provider(metadata, seed_snapshot, output_root=output_root, snapshot_day=snapshot_day)
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
    parser = argparse.ArgumentParser(description=f"Live catalog extractor for {PROVIDER_ID}.")
    parser.add_argument("--snapshot-date", default=None)
    args = parser.parse_args(argv)
    path = run_extractor(snapshot_date=args.snapshot_date)
    print(json.dumps({"provider_id": PROVIDER_ID, "snapshot_path": str(path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





















