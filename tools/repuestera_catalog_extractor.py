#!/usr/bin/env python3
"""Read-only Repuestera catalog extractor for public category and product cards."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


REPUSTERA_ROOT_URL = "https://repuestera.com.co/shop/"
DEFAULT_OUTPUT_DIR = Path("supplier_catalog/providers/repuestera/snapshots")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
CATEGORY_ITEM_START_PATTERN = re.compile(
    r'<div class="jet-woo-categories__item[^"]*"[^>]*>',
    re.IGNORECASE,
)
ITEM_START_PATTERN = re.compile(
    r'<div class="jet-listing-grid__item\b[^>]*data-post-id="(?P<post_id>\d+)"[^>]*>',
    re.IGNORECASE,
)


@dataclass
class CatalogCategory:
    category_name: str
    category_url: str
    image_url: str | None = None


@dataclass
class RepuesteraProduct:
    post_id: str
    reference: str | None
    product_name: str
    brand: str | None
    category_name: str | None
    detail_url: str
    image_url: str | None
    image_alt: str | None
    page_number: int
    source_page_url: str
    searchable_tokens: list[str] = field(default_factory=list)
    match_type: str = "manual_confirmation_required"
    match_confidence: str = "low"


def normalize_text(value: str) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def html_attr(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"""\b{re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
        attrs,
        re.IGNORECASE,
    )
    if not match:
        return None
    return unescape(next(group for group in match.groups() if group is not None))


def fetch_html(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()
        return raw.decode(charset or "utf-8", errors="replace")


def build_catalog_page_url(page_number: int) -> str:
    return REPUSTERA_ROOT_URL if page_number <= 1 else f"{REPUSTERA_ROOT_URL}page/{page_number}/"


def parse_max_page_number(html: str) -> int:
    data_page_candidates = [int(value) for value in re.findall(r"data-pages=\"(\d+)\"", html)]
    if data_page_candidates:
        return max(data_page_candidates)

    candidates = [int(value) for value in re.findall(r'"max_num_pages":(\d+)', html)]
    candidates.extend(int(value) for value in re.findall(r"/shop/page/(\d+)/", html))
    return max(candidates) if candidates else 1


def build_searchable_tokens(*values: str | None) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for value in values:
        if not value:
            continue
        for token in re.split(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ]+", value):
            normalized = normalize_text(token).lower()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            tokens.append(normalized)
    return tokens


def infer_match(reference: str | None, product_name: str, brand: str | None, category_name: str | None) -> tuple[str, str]:
    if reference:
        return "exact_reference", "high"
    if product_name and (brand or category_name):
        return "category_only", "medium"
    return "manual_confirmation_required", "low"


def parse_category_carousel(html: str) -> list[CatalogCategory]:
    categories: list[CatalogCategory] = []
    seen: set[str] = set()
    starts = list(CATEGORY_ITEM_START_PATTERN.finditer(html))
    for index, match in enumerate(starts):
        start = match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        block = html[start:end]
        title_match = re.search(
            r'<a href="([^"]+)" class="jet-woo-category-title__link"[^>]*>(.*?)</a>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        category_url = unescape(title_match.group(1))
        category_name = normalize_text(title_match.group(2))
        if not category_name or category_url in seen:
            continue
        image_match = re.search(r"<img\b([^>]*)>", block, re.IGNORECASE | re.DOTALL)
        image_url = html_attr(image_match.group(1), "src") if image_match else None
        categories.append(
            CatalogCategory(
                category_name=category_name,
                category_url=category_url,
                image_url=image_url,
            )
        )
        seen.add(category_url)
    return categories


def split_product_blocks(html: str) -> list[tuple[str, str]]:
    starts = list(ITEM_START_PATTERN.finditer(html))
    if not starts:
        return []

    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(starts):
        start = match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        blocks.append((match.group("post_id"), html[start:end]))
    return blocks


def parse_product_cards(html: str, source_page_url: str, page_number: int) -> list[RepuesteraProduct]:
    products: list[RepuesteraProduct] = []
    for post_id, block in split_product_blocks(html):
        detail_link_match = re.search(
            r'<a href="([^"]+)" class="jet-listing-dynamic-image__link">',
            block,
            re.IGNORECASE,
        )
        if not detail_link_match:
            continue
        detail_url = unescape(detail_link_match.group(1))

        image_match = re.search(r'<img\b([^>]*)class="jet-listing-dynamic-image__img[^"]*"([^>]*)>', block, re.IGNORECASE | re.DOTALL)
        image_attrs = f"{image_match.group(1)} {image_match.group(2)}" if image_match else ""
        image_url = html_attr(image_attrs, "src") if image_match else None
        image_alt = html_attr(image_attrs, "alt") if image_match else None

        dynamic_fields = re.findall(
            r'<div class="jet-listing-dynamic-field__content"\s*>(.*?)</div>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        reference = normalize_text(dynamic_fields[0]) if len(dynamic_fields) >= 1 else None
        product_name = normalize_text(dynamic_fields[1]) if len(dynamic_fields) >= 2 else (image_alt or "")
        brand_from_fields = normalize_text(dynamic_fields[2]) if len(dynamic_fields) >= 3 else None
        category_from_fields = normalize_text(dynamic_fields[3]) if len(dynamic_fields) >= 4 else None

        terms = [
            normalize_text(term)
            for term in re.findall(
                r'<span class="jet-listing-dynamic-terms__link">(.*?)</span>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if normalize_text(term)
        ]
        brand = brand_from_fields or (terms[0] if len(terms) >= 1 else None)
        category_name = category_from_fields or (terms[1] if len(terms) >= 2 else None)

        match_type, match_confidence = infer_match(reference, product_name, brand, category_name)
        searchable_tokens = build_searchable_tokens(reference, product_name, brand, category_name)

        products.append(
            RepuesteraProduct(
                post_id=post_id,
                reference=reference or None,
                product_name=product_name,
                brand=brand,
                category_name=category_name,
                detail_url=detail_url,
                image_url=image_url,
                image_alt=image_alt,
                page_number=page_number,
                source_page_url=source_page_url,
                searchable_tokens=searchable_tokens,
                match_type=match_type,
                match_confidence=match_confidence,
            )
        )
    return products


def build_diff(current_products: list[RepuesteraProduct], previous_snapshot_path: Path | None) -> dict[str, Any]:
    if not previous_snapshot_path or not previous_snapshot_path.exists():
        return {
            "previous_snapshot": None,
            "added_detail_urls": [product.detail_url for product in current_products],
            "removed_detail_urls": [],
            "changed_products": [],
        }

    previous_payload = json.loads(previous_snapshot_path.read_text(encoding="utf-8"))
    previous_products = {
        record["detail_url"]: record
        for record in previous_payload.get("products", [])
        if record.get("detail_url")
    }
    current_map = {product.detail_url: product for product in current_products}

    added = [url for url in current_map if url not in previous_products]
    removed = [url for url in previous_products if url not in current_map]
    changed_products: list[dict[str, Any]] = []

    for url, product in current_map.items():
        old = previous_products.get(url)
        if not old:
            continue
        changes: dict[str, Any] = {}
        for field_name in ("reference", "product_name", "brand", "category_name"):
            old_value = old.get(field_name)
            new_value = getattr(product, field_name)
            if old_value != new_value:
                changes[field_name] = {"old": old_value, "new": new_value}
        if changes:
            changed_products.append({"detail_url": url, "changes": changes})

    return {
        "previous_snapshot": str(previous_snapshot_path),
        "added_detail_urls": added,
        "removed_detail_urls": removed,
        "changed_products": changed_products,
    }


def previous_snapshot_file(output_dir: Path, snapshot_date: str) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(
        path / "extracted.json"
        for path in output_dir.iterdir()
        if path.is_dir() and path.name < snapshot_date and (path / "extracted.json").exists()
    )
    return candidates[-1] if candidates else None


def write_csv(path: Path, products: list[RepuesteraProduct]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "post_id",
                "reference",
                "product_name",
                "brand",
                "category_name",
                "detail_url",
                "image_url",
                "page_number",
                "match_type",
                "match_confidence",
            ],
        )
        writer.writeheader()
        for product in products:
            writer.writerow(
                {
                    "post_id": product.post_id,
                    "reference": product.reference,
                    "product_name": product.product_name,
                    "brand": product.brand,
                    "category_name": product.category_name,
                    "detail_url": product.detail_url,
                    "image_url": product.image_url,
                    "page_number": product.page_number,
                    "match_type": product.match_type,
                    "match_confidence": product.match_confidence,
                }
            )


def write_summary(path: Path, payload: dict[str, Any], diff: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Repuestera Snapshot Summary - {payload['snapshot_date']}",
        "",
        f"Carousel categories extracted: {payload['summary']['carousel_categories_extracted']}",
        f"Products extracted: {payload['summary']['products_extracted']}",
        f"Pages scanned: {payload['summary']['pages_scanned']}",
        f"Products with reference: {payload['summary']['products_with_reference']}",
        f"Products with brand: {payload['summary']['products_with_brand']}",
        f"Products with category: {payload['summary']['products_with_category']}",
        f"Added products vs previous snapshot: {len(diff['added_detail_urls'])}",
        f"Removed products vs previous snapshot: {len(diff['removed_detail_urls'])}",
        f"Changed products vs previous snapshot: {len(diff['changed_products'])}",
        "",
        "This snapshot is read-only and intended for supplier matching.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_catalog(max_pages: int | None = None, user_agent: str = DEFAULT_USER_AGENT) -> tuple[list[CatalogCategory], list[RepuesteraProduct], int]:
    first_page_html = fetch_html(REPUSTERA_ROOT_URL, user_agent=user_agent)
    categories = parse_category_carousel(first_page_html)
    page_count = parse_max_page_number(first_page_html)
    if max_pages is not None:
        page_count = min(page_count, max_pages)

    products: list[RepuesteraProduct] = []
    seen_urls: set[str] = set()
    pages_scanned = 0

    first_page_products = parse_product_cards(first_page_html, REPUSTERA_ROOT_URL, 1)
    for product in first_page_products:
        if product.detail_url not in seen_urls:
            products.append(product)
            seen_urls.add(product.detail_url)
    pages_scanned = 1

    for page_number in range(2, page_count + 1):
        page_url = build_catalog_page_url(page_number)
        html = fetch_html(page_url, user_agent=user_agent)
        page_products = parse_product_cards(html, page_url, page_number)
        new_products = [product for product in page_products if product.detail_url not in seen_urls]
        pages_scanned += 1
        if not new_products:
            break
        for product in new_products:
            products.append(product)
            seen_urls.add(product.detail_url)
    return categories, products, pages_scanned


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-date", default=str(date.today()))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--csv-output", type=Path, default=None)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--diff-output", type=Path, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    snapshot_dir = args.output_root / args.snapshot_date
    json_output = args.json_output or snapshot_dir / "extracted.json"
    csv_output = args.csv_output or snapshot_dir / "products.csv"
    summary_output = args.summary_output or snapshot_dir / "summary.md"
    diff_output = args.diff_output or snapshot_dir / "diff.json"

    categories, products, page_count = extract_catalog(max_pages=args.max_pages, user_agent=args.user_agent)
    previous_snapshot = previous_snapshot_file(args.output_root, args.snapshot_date)
    diff = build_diff(products, previous_snapshot)

    payload = {
        "provider_id": "repuestera",
        "provider_name": "Repuestera",
        "snapshot_date": args.snapshot_date,
        "timezone": "America/Bogota",
        "catalog_root_url": REPUSTERA_ROOT_URL,
        "category_carousel": [asdict(category) for category in categories],
        "products": [asdict(product) for product in products],
        "summary": {
            "carousel_categories_extracted": len(categories),
            "products_extracted": len(products),
            "pages_scanned": page_count,
            "products_with_reference": sum(1 for product in products if product.reference),
            "products_with_brand": sum(1 for product in products if product.brand),
            "products_with_category": sum(1 for product in products if product.category_name),
        },
    }

    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(csv_output, products)
    diff_output.write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_summary(summary_output, payload, diff)

    print(
        f"Extracted {len(products)} Repuestera product(s) across {page_count} page(s). "
        f"Output: {json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
