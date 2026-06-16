#!/usr/bin/env python3
"""Read-only Partcar public catalog extractor using dynamic_page pagination."""

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
from urllib.parse import urljoin
from urllib.request import Request, urlopen


PARTCAR_CATALOG_URL = "https://www.partcar.com.co/importacion-1"
DEFAULT_OUTPUT_DIR = Path("supplier_catalog/providers/partcar/snapshots")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


@dataclass
class PartcarProduct:
    product_name: str
    supplier_item_code: str | None
    detail_url: str
    image_url: str | None
    image_alt: str | None
    page_number: int
    source_page_url: str
    taxonomy_label: str
    searchable_tokens: list[str] = field(default_factory=list)
    match_type: str = "category_only"
    match_confidence: str = "medium"
    requires_manual_confirmation: bool = True


def normalize_text(value: str) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_html(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()
        return raw.decode(charset or "utf-8", errors="replace")


def build_catalog_page_url(page_number: int) -> str:
    return PARTCAR_CATALOG_URL if page_number <= 1 else f"{PARTCAR_CATALOG_URL}?dynamic_page={page_number}"


def parse_next_page_number(html: str) -> int | None:
    match = re.search(r'<link rel="next" href="[^"]*dynamic_page=(\d+)"', html, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def split_listitem_blocks(html: str) -> list[str]:
    starts = list(re.finditer(r'role="listitem"\s+class="_FiCX">', html, re.IGNORECASE))
    blocks: list[str] = []
    for index, match in enumerate(starts):
        start = match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        blocks.append(html[start:end])
    return blocks


def infer_taxonomy(product_name: str) -> tuple[str, str]:
    lowered = product_name.lower()
    if "farola" in lowered:
        return "lighting_headlamps", "medium"
    if "stop" in lowered:
        return "lighting_tail_lamps", "medium"
    if "espejo" in lowered:
        return "mirrors", "medium"
    if "parachoque" in lowered or "bumper" in lowered:
        return "body_exterior", "medium"
    if "capo" in lowered:
        return "body_exterior", "medium"
    if "guardafango" in lowered:
        return "body_exterior", "medium"
    if "rejilla" in lowered:
        return "front_grille", "medium"
    return "manual_review", "low"


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


def parse_product_cards(html: str, source_page_url: str, page_number: int) -> list[PartcarProduct]:
    products: list[PartcarProduct] = []
    for block in split_listitem_blocks(html):
        link_match = re.search(r'<a[^>]+data-testid="linkElement"[^>]+href="([^"]+)"', block, re.IGNORECASE)
        title_match = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.IGNORECASE | re.DOTALL)
        paragraph_values = [
            normalize_text(value)
            for value in re.findall(r"<p[^>]*>(.*?)</p>", block, re.IGNORECASE | re.DOTALL)
        ]
        image_match = re.search(r'<img[^>]+src="([^"]+)"[^>]+alt="([^"]*)"', block, re.IGNORECASE | re.DOTALL)

        if not link_match or not title_match:
            continue

        detail_url = urljoin(PARTCAR_CATALOG_URL, unescape(link_match.group(1)))
        product_name = normalize_text(title_match.group(1))
        supplier_item_code = next((value for value in paragraph_values if re.fullmatch(r"\d{3,}", value)), None)
        image_url = unescape(image_match.group(1)) if image_match else None
        image_alt = unescape(image_match.group(2)) if image_match else None
        taxonomy_label, match_confidence = infer_taxonomy(product_name)
        match_type = "category_only" if taxonomy_label != "manual_review" else "manual_confirmation_required"

        products.append(
            PartcarProduct(
                product_name=product_name,
                supplier_item_code=supplier_item_code,
                detail_url=detail_url,
                image_url=image_url,
                image_alt=image_alt,
                page_number=page_number,
                source_page_url=source_page_url,
                taxonomy_label=taxonomy_label,
                searchable_tokens=build_searchable_tokens(product_name, supplier_item_code, image_alt),
                match_type=match_type,
                match_confidence=match_confidence,
            )
        )
    return products


def previous_snapshot_file(output_dir: Path, snapshot_date: str) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(
        path / "extracted.json"
        for path in output_dir.iterdir()
        if path.is_dir() and path.name < snapshot_date and (path / "extracted.json").exists()
    )
    return candidates[-1] if candidates else None


def build_diff(current_products: list[PartcarProduct], previous_snapshot_path: Path | None) -> dict[str, Any]:
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
        for field_name in ("product_name", "supplier_item_code", "taxonomy_label"):
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


def write_csv(path: Path, products: list[PartcarProduct]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "product_name",
                "supplier_item_code",
                "detail_url",
                "image_url",
                "page_number",
                "taxonomy_label",
                "match_type",
                "match_confidence",
            ],
        )
        writer.writeheader()
        for product in products:
            writer.writerow(
                {
                    "product_name": product.product_name,
                    "supplier_item_code": product.supplier_item_code,
                    "detail_url": product.detail_url,
                    "image_url": product.image_url,
                    "page_number": product.page_number,
                    "taxonomy_label": product.taxonomy_label,
                    "match_type": product.match_type,
                    "match_confidence": product.match_confidence,
                }
            )


def write_summary(path: Path, payload: dict[str, Any], diff: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Partcar Snapshot Summary - {payload['snapshot_date']}",
        "",
        f"Products extracted: {payload['summary']['products_extracted']}",
        f"Pages scanned: {payload['summary']['pages_scanned']}",
        f"Products with supplier code: {payload['summary']['products_with_supplier_code']}",
        f"Products with detail URL: {payload['summary']['products_with_detail_url']}",
        f"Products with classified taxonomy: {payload['summary']['products_with_known_taxonomy']}",
        f"Added products vs previous snapshot: {len(diff['added_detail_urls'])}",
        f"Removed products vs previous snapshot: {len(diff['removed_detail_urls'])}",
        f"Changed products vs previous snapshot: {len(diff['changed_products'])}",
        "",
        "Visible numeric codes are treated as supplier catalog codes, not exact OEM references.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_catalog(max_pages: int | None = None, user_agent: str = DEFAULT_USER_AGENT) -> tuple[list[PartcarProduct], int]:
    products: list[PartcarProduct] = []
    seen_urls: set[str] = set()
    page_number = 1
    pages_scanned = 0

    while True:
        if max_pages is not None and page_number > max_pages:
            break
        page_url = build_catalog_page_url(page_number)
        html = fetch_html(page_url, user_agent=user_agent)
        page_products = parse_product_cards(html, page_url, page_number)
        new_products = [product for product in page_products if product.detail_url not in seen_urls]
        pages_scanned += 1
        if not new_products and page_number > 1:
            break
        for product in new_products:
            products.append(product)
            seen_urls.add(product.detail_url)
        next_page_number = parse_next_page_number(html)
        if not next_page_number:
            break
        page_number = next_page_number
    return products, pages_scanned


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

    products, page_count = extract_catalog(max_pages=args.max_pages, user_agent=args.user_agent)
    previous_snapshot = previous_snapshot_file(args.output_root, args.snapshot_date)
    diff = build_diff(products, previous_snapshot)

    payload = {
        "provider_id": "partcar",
        "provider_name": "Partcar",
        "snapshot_date": args.snapshot_date,
        "timezone": "America/Bogota",
        "catalog_root_url": PARTCAR_CATALOG_URL,
        "products": [asdict(product) for product in products],
        "summary": {
            "products_extracted": len(products),
            "pages_scanned": page_count,
            "products_with_supplier_code": sum(1 for product in products if product.supplier_item_code),
            "products_with_detail_url": sum(1 for product in products if product.detail_url),
            "products_with_known_taxonomy": sum(1 for product in products if product.taxonomy_label != "manual_review"),
        },
    }

    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(csv_output, products)
    diff_output.write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_summary(summary_output, payload, diff)

    print(
        f"Extracted {len(products)} Partcar product(s) across {page_count} page(s). "
        f"Output: {json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
