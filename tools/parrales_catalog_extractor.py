#!/usr/bin/env python3
"""Read-only Parrales catalog extractor for individual product records."""

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


PARRALES_ROOT_URL = "https://parrales.com.co/tienda/"
DEFAULT_OUTPUT_DIR = Path("supplier_catalog/providers/parrales/snapshots")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
TOP_LEVEL_CATEGORY_SLUGS = {
    "cables-electricos",
    "iluminacion",
    "lujos-y-accesorios",
    "miscelanea-electrica",
    "pitos",
    "plumillas-limpiaparabrisas",
    "repuestos-electricos",
    "repuestos-mecanicos",
}
LISTING_PRODUCT_PATTERN = re.compile(
    r'<li class="(?P<class>[^"]*\bproduct\b[^"]*)"[^>]*>(?P<body>.*?)</li>\s*(?=<li class="[^"]*\bproduct\b|</ul>)',
    re.IGNORECASE | re.DOTALL,
)
FILTER_CATEGORY_PATTERN = re.compile(
    r'<a[^>]+href="(?:https://parrales\.com\.co)?/product-category/([^"/]+)/?[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def repair_mojibake(value: str) -> str:
    if not value or not any(marker in value for marker in ("Ã", "Â", "â€", "â€“", "â€¢")):
        return value
    try:
        repaired = value.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
    except UnicodeError:
        return value
    return repaired or value


@dataclass
class ListingProduct:
    product_id: str | None
    product_name: str
    product_url: str
    image_url: str | None
    price_current: int | None
    price_original: int | None
    on_sale: bool
    currency: str
    listing_description: str | None
    listing_attributes: dict[str, str] = field(default_factory=dict)
    sku: str | None = None
    category_slug: str | None = None
    category_name: str | None = None
    subcategory_slug: str | None = None
    subcategory_name: str | None = None
    category_slugs: list[str] = field(default_factory=list)
    raw_badge: str | None = None


@dataclass
class ExtractedParralesProduct:
    product_id: str | None
    product_name: str
    product_url: str
    image_url: str | None
    price_current: int | None
    price_original: int | None
    on_sale: bool
    currency: str
    brand: str | None
    reference: str | None
    sku: str | None
    category_slug: str | None
    category_name: str | None
    subcategory_slug: str | None
    subcategory_name: str | None
    category_slugs: list[str]
    short_description: str | None
    description: str | None
    technical_attributes: dict[str, str] = field(default_factory=dict)
    searchable_tokens: list[str] = field(default_factory=list)
    match_type: str = "manual_confirmation_required"
    match_confidence: str = "low"
    requires_manual_confirmation: bool = True
    warnings: list[str] = field(default_factory=list)


def normalize_text(value: str) -> str:
    text = repair_mojibake(unescape(value or ""))
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_tags(value: str) -> str:
    return normalize_text(value)


def html_attr(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"""\b{re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
        attrs,
        re.IGNORECASE,
    )
    if not match:
        return None
    return unescape(next(group for group in match.groups() if group is not None))


def slug_to_name(slug: str) -> str:
    text = slug.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", text).strip().title()


def parse_price_to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", unescape(value))
    return int(digits) if digits else None


def fetch_html(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()
        if charset:
            return raw.decode(charset, errors="replace")
        decoded = raw.decode("utf-8", errors="replace")
        if "Ã" in decoded or "â€“" in decoded or "Â" in decoded:
            try:
                repaired = decoded.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
                if repaired:
                    return repaired
            except UnicodeError:
                pass
        return decoded


def parse_filter_taxonomy(html: str) -> dict[str, str]:
    taxonomy: dict[str, str] = {}
    for slug, label_html in FILTER_CATEGORY_PATTERN.findall(html):
        normalized_slug = slug.strip("/").strip()
        if normalized_slug and normalized_slug not in taxonomy:
            taxonomy[normalized_slug] = normalize_text(label_html)
    return taxonomy


def split_category_slugs(class_attr: str) -> list[str]:
    slugs: list[str] = []
    for slug in re.findall(r"\bproduct_cat-([a-z0-9\-]+)\b", class_attr, re.IGNORECASE):
        if slug not in slugs:
            slugs.append(slug)
    return slugs


def assign_category_names(category_slugs: list[str], taxonomy: dict[str, str]) -> tuple[str | None, str | None, str | None, str | None]:
    if not category_slugs:
        return None, None, None, None

    category_slug: str | None = None
    subcategory_slug: str | None = None

    for slug in category_slugs:
        if slug in TOP_LEVEL_CATEGORY_SLUGS:
            category_slug = slug
        elif subcategory_slug is None:
            subcategory_slug = slug

    if category_slug is None:
        category_slug = category_slugs[-1]
    if subcategory_slug is None and len(category_slugs) > 1:
        for slug in category_slugs:
            if slug != category_slug:
                subcategory_slug = slug
                break

    category_name = taxonomy.get(category_slug, slug_to_name(category_slug)) if category_slug else None
    subcategory_name = (
        taxonomy.get(subcategory_slug, slug_to_name(subcategory_slug))
        if subcategory_slug
        else None
    )
    return category_slug, category_name, subcategory_slug, subcategory_name


def parse_listing_attributes(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    compact = normalize_text(value)
    attributes: dict[str, str] = {}
    for label, attribute_value in re.findall(r"([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-z0-9 /_-]+):\s*([^:]+?)(?=\s+[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-z0-9 /_-]+:|$)", compact):
        normalized_label = normalize_text(label).lower()
        normalized_value = normalize_text(attribute_value)
        if normalized_label and normalized_value:
            attributes[normalized_label] = normalized_value
    return attributes


def parse_listing_products(html: str, taxonomy: dict[str, str]) -> list[ListingProduct]:
    products: list[ListingProduct] = []
    for match in LISTING_PRODUCT_PATTERN.finditer(html):
        class_attr = match.group("class")
        block = match.group("body")

        title_match = re.search(
            r"<h4>\s*<a[^>]+href=\"([^\"]+)\"[^>]*(?:title=\"([^\"]*)\")?[^>]*>(.*?)</a>\s*</h4>",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        product_url = unescape(title_match.group(1))
        title = normalize_text(title_match.group(2) or title_match.group(3))

        img_match = re.search(r"<img\b([^>]*)>", block, re.IGNORECASE | re.DOTALL)
        image_url = html_attr(img_match.group(1), "src") if img_match else None

        price_match = re.search(
            r"<span class=\"item-price\">([\s\S]*?)</span>\s*(?:<div class=\"item-description\">|<div class=\"item-bottom)",
            block,
            re.IGNORECASE,
        )
        price_html = price_match.group(1) if price_match else ""
        original_match = re.search(r"<del[^>]*>.*?<bdi>.*?(\d[\d\.]*)</bdi>.*?</del>", price_html, re.IGNORECASE | re.DOTALL)
        current_match = re.search(r"<ins[^>]*>.*?<bdi>.*?(\d[\d\.]*)</bdi>.*?</ins>", price_html, re.IGNORECASE | re.DOTALL)
        plain_current_match = re.search(r"<bdi>.*?(\d[\d\.]*)</bdi>", price_html, re.IGNORECASE | re.DOTALL)
        price_original = parse_price_to_int(original_match.group(1) if original_match else None)
        if current_match:
            price_current = parse_price_to_int(current_match.group(1))
            on_sale = True
        else:
            price_current = parse_price_to_int(plain_current_match.group(1) if plain_current_match else None)
            on_sale = False

        desc_match = re.search(
            r"<div class=\"item-description\">(.*?)</div>",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        listing_description_html = desc_match.group(1) if desc_match else None
        listing_description = normalize_text(listing_description_html or "")
        listing_attributes = parse_listing_attributes(listing_description)

        badge_match = re.search(r"<div class=\"sale-off[^\"]*\">(.*?)</div>", block, re.IGNORECASE | re.DOTALL)
        badge_text = normalize_text(badge_match.group(1)) if badge_match else None

        add_to_cart_match = re.search(r"(<a\b[^>]*class=\"[^\"]*add_to_cart_button[^\"]*\"[^>]*>)", block, re.IGNORECASE | re.DOTALL)
        add_to_cart_attrs = add_to_cart_match.group(1) if add_to_cart_match else ""
        product_id = html_attr(add_to_cart_attrs, "data-product_id")
        sku = html_attr(add_to_cart_attrs, "data-product_sku")

        category_slugs = split_category_slugs(class_attr)
        category_slug, category_name, subcategory_slug, subcategory_name = assign_category_names(category_slugs, taxonomy)

        products.append(
            ListingProduct(
                product_id=product_id,
                product_name=title,
                product_url=product_url,
                image_url=image_url,
                price_current=price_current,
                price_original=price_original,
                on_sale=on_sale,
                currency="COP",
                listing_description=listing_description or None,
                listing_attributes=listing_attributes,
                sku=sku,
                category_slug=category_slug,
                category_name=category_name,
                subcategory_slug=subcategory_slug,
                subcategory_name=subcategory_name,
                category_slugs=category_slugs,
                raw_badge=badge_text,
            )
        )
    return products


def enrich_taxonomy_from_listing_products(
    taxonomy: dict[str, str],
    listing_products: list[ListingProduct],
) -> dict[str, str]:
    enriched = dict(taxonomy)
    for product in listing_products:
        if product.category_slug and product.category_name:
            enriched.setdefault(product.category_slug, product.category_name)
        if product.subcategory_slug and product.subcategory_name:
            enriched.setdefault(product.subcategory_slug, product.subcategory_name)
    return enriched


def extract_short_description(html: str) -> str | None:
    match = re.search(
        r'<div class="woocommerce-product-details__short-description">\s*(.*?)\s*</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return strip_tags(match.group(1)) if match else None


def extract_description(html: str) -> str | None:
    match = re.search(
        r'<div class="tab-pane active" id="tab-description">\s*(.*?)\s*</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return strip_tags(match.group(1)) if match else None


def extract_title(html: str) -> str | None:
    match = re.search(
        r'<h1 class="product_title[^"]*">(.*?)</h1>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return normalize_text(match.group(1)) if match else None


def extract_brand(html: str) -> str | None:
    brand_match = re.search(
        r'<div class="item-brand">.*?<a[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if brand_match:
        return normalize_text(brand_match.group(1))
    return None


def extract_sku(html: str) -> str | None:
    match = re.search(
        r'<span class="sku_wrapper">SKU:\s*<span class="sku"[^>]*>(.*?)</span>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return normalize_text(match.group(1)) if match else None


def extract_meta_price(html: str) -> tuple[int | None, str]:
    price_match = re.search(r'<meta itemprop="price" content="(\d+)"', html, re.IGNORECASE)
    currency_match = re.search(r'<meta itemprop="priceCurrency" content="([A-Z]+)"', html, re.IGNORECASE)
    return (int(price_match.group(1)) if price_match else None, currency_match.group(1) if currency_match else "COP")


def extract_original_price(html: str) -> int | None:
    match = re.search(r"Original price was:\s*&#036;&nbsp;([\d\.]+)", html, re.IGNORECASE)
    return parse_price_to_int(match.group(1) if match else None)


def extract_image_url(html: str) -> str | None:
    match = re.search(
        r'<meta property="og:image" content="([^"]+)"',
        html,
        re.IGNORECASE,
    )
    return unescape(match.group(1)) if match else None


def extract_detail_attributes(html: str) -> dict[str, str]:
    short_description_match = re.search(
        r'<div class="woocommerce-product-details__short-description">\s*(.*?)\s*</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    detail_attributes: dict[str, str] = {}
    if short_description_match:
        short_text = strip_tags(short_description_match.group(1).replace("<br />", "\n").replace("<br>", "\n"))
        for label, value in re.findall(
            r"([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-z0-9 /_-]+):\s*([^\n]+)",
            short_text,
        ):
            key = normalize_text(label).lower()
            val = normalize_text(value)
            if key and val:
                detail_attributes[key] = val

    for label, value in re.findall(
        r"<strong[^>]*>([^:<]+):</strong>\s*([^<]+)",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        key = normalize_text(label).lower()
        val = normalize_text(value)
        if key and val:
            detail_attributes[key] = val
    return detail_attributes


def extract_reference_from_name(product_name: str) -> str | None:
    match = re.search(r"\(([A-Z0-9][A-Z0-9/\-_,. ]{2,})\)", product_name)
    if match:
        return normalize_text(match.group(1))
    return None


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


def infer_match(reference: str | None, sku: str | None, technical_attributes: dict[str, str]) -> tuple[str, str, bool]:
    if reference:
        return "exact_reference", "high", False
    if sku:
        return "exact_reference", "medium", False
    if any(key in technical_attributes for key in ("compatibilidad", "aplicacion", "uso")):
        return "vehicle_compatible", "medium", True
    if technical_attributes:
        return "category_only", "medium", True
    return "manual_confirmation_required", "low", True


def parse_product_detail(html: str, listing_product: ListingProduct) -> ExtractedParralesProduct:
    detail_attributes = extract_detail_attributes(html)
    brand = (
        detail_attributes.get("marca")
        or extract_brand(html)
        or listing_product.listing_attributes.get("marca")
    )
    reference = (
        detail_attributes.get("ref")
        or detail_attributes.get("referencia")
        or listing_product.listing_attributes.get("ref")
        or extract_reference_from_name(listing_product.product_name)
    )
    sku = extract_sku(html) or listing_product.sku
    price_current, currency = extract_meta_price(html)
    price_original = extract_original_price(html) or listing_product.price_original
    short_description = extract_short_description(html) or listing_product.listing_description
    description = extract_description(html)
    match_type, match_confidence, requires_manual_confirmation = infer_match(reference, sku, detail_attributes)
    product_name = extract_title(html) or listing_product.product_name
    image_url = extract_image_url(html) or listing_product.image_url

    searchable_tokens = build_searchable_tokens(
        product_name,
        brand,
        reference,
        sku,
        short_description,
        description,
        listing_product.category_name,
        listing_product.subcategory_name,
    )

    warnings: list[str] = []
    if not description:
        warnings.append("Description tab was not found on the product detail page.")
    if not brand:
        warnings.append("Brand was not found in structured product fields.")

    return ExtractedParralesProduct(
        product_id=listing_product.product_id,
        product_name=product_name,
        product_url=listing_product.product_url,
        image_url=image_url,
        price_current=price_current or listing_product.price_current,
        price_original=price_original,
        on_sale=listing_product.on_sale or price_original is not None,
        currency=currency or listing_product.currency,
        brand=brand,
        reference=reference,
        sku=sku,
        category_slug=listing_product.category_slug,
        category_name=listing_product.category_name,
        subcategory_slug=listing_product.subcategory_slug,
        subcategory_name=listing_product.subcategory_name,
        category_slugs=listing_product.category_slugs,
        short_description=short_description,
        description=description,
        technical_attributes=detail_attributes,
        searchable_tokens=searchable_tokens,
        match_type=match_type,
        match_confidence=match_confidence,
        requires_manual_confirmation=requires_manual_confirmation,
        warnings=warnings,
    )


def parse_max_page_number(html: str) -> int:
    matches = [int(value) for value in re.findall(r"/tienda/page/(\d+)/", html)]
    return max(matches) if matches else 1


def build_catalog_page_url(page_number: int) -> str:
    return PARRALES_ROOT_URL if page_number <= 1 else f"{PARRALES_ROOT_URL}page/{page_number}/"


def build_diff(current_products: list[ExtractedParralesProduct], previous_snapshot_path: Path | None) -> dict[str, Any]:
    if not previous_snapshot_path or not previous_snapshot_path.exists():
        return {
            "previous_snapshot": None,
            "added_product_urls": [product.product_url for product in current_products],
            "removed_product_urls": [],
            "price_changes": [],
        }

    previous_payload = json.loads(previous_snapshot_path.read_text(encoding="utf-8"))
    previous_products = {
        record["product_url"]: record
        for record in previous_payload.get("products", [])
        if record.get("product_url")
    }
    current_map = {product.product_url: product for product in current_products}

    added = [url for url in current_map if url not in previous_products]
    removed = [url for url in previous_products if url not in current_map]
    price_changes: list[dict[str, Any]] = []
    for url, product in current_map.items():
        old = previous_products.get(url)
        if not old:
            continue
        if old.get("price_current") != product.price_current:
            price_changes.append(
                {
                    "product_url": url,
                    "old_price_current": old.get("price_current"),
                    "new_price_current": product.price_current,
                }
            )

    return {
        "previous_snapshot": str(previous_snapshot_path),
        "added_product_urls": added,
        "removed_product_urls": removed,
        "price_changes": price_changes,
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


def write_csv(path: Path, products: list[ExtractedParralesProduct]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "product_id",
                "product_name",
                "product_url",
                "price_current",
                "price_original",
                "brand",
                "reference",
                "sku",
                "category_name",
                "subcategory_name",
                "match_type",
                "match_confidence",
                "requires_manual_confirmation",
            ],
        )
        writer.writeheader()
        for product in products:
            writer.writerow(
                {
                    "product_id": product.product_id,
                    "product_name": product.product_name,
                    "product_url": product.product_url,
                    "price_current": product.price_current,
                    "price_original": product.price_original,
                    "brand": product.brand,
                    "reference": product.reference,
                    "sku": product.sku,
                    "category_name": product.category_name,
                    "subcategory_name": product.subcategory_name,
                    "match_type": product.match_type,
                    "match_confidence": product.match_confidence,
                    "requires_manual_confirmation": product.requires_manual_confirmation,
                }
            )


def write_summary(path: Path, payload: dict[str, Any], diff: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Parrales Snapshot Summary - {payload['snapshot_date']}",
        "",
        f"Products extracted: {payload['summary']['products_extracted']}",
        f"Pages scanned: {payload['summary']['pages_scanned']}",
        f"Categories observed: {payload['summary']['categories_observed']}",
        f"Products with reference: {payload['summary']['products_with_reference']}",
        f"Products with SKU: {payload['summary']['products_with_sku']}",
        f"Products with brand: {payload['summary']['products_with_brand']}",
        f"Added products vs previous snapshot: {len(diff['added_product_urls'])}",
        f"Removed products vs previous snapshot: {len(diff['removed_product_urls'])}",
        f"Price changes vs previous snapshot: {len(diff['price_changes'])}",
        "",
        "This snapshot is read-only and intended for catalog matching.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_catalog(max_pages: int | None = None, user_agent: str = DEFAULT_USER_AGENT) -> tuple[dict[str, str], list[ExtractedParralesProduct], int]:
    first_page_html = fetch_html(PARRALES_ROOT_URL, user_agent=user_agent)
    taxonomy = parse_filter_taxonomy(first_page_html)
    page_count = parse_max_page_number(first_page_html)
    if max_pages is not None:
        page_count = min(page_count, max_pages)

    listing_products: list[ListingProduct] = []
    listing_products.extend(parse_listing_products(first_page_html, taxonomy))
    for page_number in range(2, page_count + 1):
        html = fetch_html(build_catalog_page_url(page_number), user_agent=user_agent)
        listing_products.extend(parse_listing_products(html, taxonomy))

    taxonomy = enrich_taxonomy_from_listing_products(taxonomy, listing_products)

    extracted_products: list[ExtractedParralesProduct] = []
    for listing_product in listing_products:
        detail_html = fetch_html(listing_product.product_url, user_agent=user_agent)
        extracted_products.append(parse_product_detail(detail_html, listing_product))
    return taxonomy, extracted_products, page_count


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

    taxonomy, products, page_count = extract_catalog(max_pages=args.max_pages, user_agent=args.user_agent)
    previous_snapshot = previous_snapshot_file(args.output_root, args.snapshot_date)
    diff = build_diff(products, previous_snapshot)

    payload = {
        "provider_id": "parrales",
        "provider_name": "Parrales",
        "snapshot_date": args.snapshot_date,
        "timezone": "America/Bogota",
        "catalog_root_url": PARRALES_ROOT_URL,
        "categories": taxonomy,
        "products": [asdict(product) for product in products],
        "summary": {
            "products_extracted": len(products),
            "pages_scanned": page_count,
            "categories_observed": len(taxonomy),
            "products_with_reference": sum(1 for product in products if product.reference),
            "products_with_sku": sum(1 for product in products if product.sku),
            "products_with_brand": sum(1 for product in products if product.brand),
        },
    }

    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(csv_output, products)
    diff_output.write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_summary(summary_output, payload, diff)

    print(
        f"Extracted {len(products)} Parrales product(s) across {page_count} page(s). "
        f"Output: {json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
