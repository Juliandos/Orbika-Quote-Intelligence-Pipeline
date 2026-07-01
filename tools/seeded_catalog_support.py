#!/usr/bin/env python3
"""Shared low-level helpers for provider-specific seeded catalog extractors."""

from __future__ import annotations

import csv
import gzip
import json
import re
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
PROVIDERS_ROOT = Path("supplier_catalog/providers")
AUTOS_ONLY_NOTE = "Extraction is limited to autos surfaces only; motos and heavy-duty lines are intentionally excluded."
MANUAL_NOTE = "Public data remains partial and should be treated as supplier-verification support."


@dataclass
class ProductRecord:
    item_type: str
    provider_type: str
    title: str | None = None
    product_name: str | None = None
    detail_url: str | None = None
    product_url: str | None = None
    category_name: str | None = None
    subcategory_name: str | None = None
    brand: str | None = None
    reference: str | None = None
    sku: str | None = None
    supplier_item_code: str | None = None
    description: str | None = None
    vehicle_scope: str | None = None
    image_url: str | None = None
    source_page_url: str | None = None
    page_number: int = 1
    match_type: str = "manual_confirmation_required"
    match_confidence: str = "low"
    requires_manual_confirmation: bool = True
    searchable_tokens: list[str] = field(default_factory=list)


def normalize_text(value: str | None) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slug_to_words(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"[-_/]+", " ", value)
    return normalize_text(text)


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def same_host(url: str, allowed_host: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == allowed_host or host.endswith(f".{allowed_host}")


def guess_page_number(url: str) -> int:
    page_match = re.search(r"(?:[?&](?:page|paged|pageNumber|product-page)=|/page/)(\d+)", url, re.IGNORECASE)
    return int(page_match.group(1)) if page_match else 1


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


def fetch_url(url: str, user_agent: str = DEFAULT_USER_AGENT) -> tuple[str, bytes, dict[str, str]]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip",
        },
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        final_url = response.geturl()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return final_url, raw, headers


def decode_html(raw: bytes, headers: dict[str, str]) -> str:
    charset = None
    content_type = headers.get("content-type", "")
    charset_match = re.search(r"charset=([A-Za-z0-9_\-]+)", content_type, re.IGNORECASE)
    if charset_match:
        charset = charset_match.group(1)
    text = raw.decode(charset or "utf-8", errors="replace")
    if any(marker in text for marker in ("Ã", "Â", "â€")):
        try:
            repaired = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        except UnicodeError:
            return text
        if repaired:
            return repaired
    return text


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def provider_paths(provider_id: str) -> tuple[Path, Path]:
    provider_dir = PROVIDERS_ROOT / provider_id
    snapshots_root = provider_dir / "snapshots"
    return provider_dir, snapshots_root


def latest_snapshot_json(provider_id: str) -> Path | None:
    provider_dir, snapshots_root = provider_paths(provider_id)
    if not provider_dir.exists() or not snapshots_root.exists():
        return None
    extracted = sorted(snapshots_root.glob("*/extracted.json"))
    return extracted[-1] if extracted else None


def entry_urls_from_snapshot(snapshot: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for record in snapshot.get("products", []):
        if not isinstance(record, dict):
            continue
        for field_name in ("source_page_url", "product_url", "detail_url", "category_url", "brand_url", "url"):
            value = record.get(field_name)
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)
    for record in snapshot.get("categories", []):
        if isinstance(record, dict):
            for field_name in ("category_url", "detail_url", "url"):
                value = record.get(field_name)
                if isinstance(value, str) and value.startswith("http"):
                    urls.append(value)
    for record in snapshot.get("brand_pages", []):
        if isinstance(record, dict):
            value = record.get("brand_url")
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)
    return urls


def default_product_like_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        token in lowered
        for token in ("/producto/", "/product/", "/products/", "/product-page/", "/producto-", "/ampliacion/")
    ) or lowered.endswith(".html")


def default_category_like_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        token in lowered
        for token in (
            "/categoria-producto/",
            "/product-category/",
            "/collections/",
            "/category/",
            "/categorias/",
            "/catalogo",
            "/productos/",
            "/portafolio/",
            "/autos/",
            "/tienda/",
            "/all-products",
            "/productos-categoria/",
        )
    )


def ignored_by_keywords(value: str, exclude_keywords: Iterable[str]) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in ("/feed/", ".rss", ".xml")):
        return True
    return any(keyword in lowered for keyword in exclude_keywords)


def url_matches_any(url: str, patterns: Iterable[str]) -> bool:
    lowered = url.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def extract_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in re.findall(r"""href\s*=\s*(?:"([^"]+)"|'([^']+)')""", html, re.IGNORECASE):
        value = href[0] or href[1]
        if not value or value.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        if any(marker in value.lower() for marker in ("/feed/", ".rss", ".xml")):
            continue
        absolute = canonical_url(urljoin(base_url, unescape(value)))
        if absolute not in seen:
            links.append(absolute)
            seen.add(absolute)
    return links


def parse_json_ld_blocks(html: str) -> list[Any]:
    blocks: list[Any] = []
    for raw_block in re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        candidate = raw_block.strip()
        if not candidate:
            continue
        try:
            blocks.append(json.loads(candidate))
            continue
        except json.JSONDecodeError:
            try:
                cleaned = re.sub(r"[\x00-\x1f]+", " ", candidate)
                blocks.append(json.loads(cleaned))
            except json.JSONDecodeError:
                continue
    return blocks


def iter_json_ld_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "@graph" in value and isinstance(value["@graph"], list):
            for item in value["@graph"]:
                yield from iter_json_ld_nodes(item)
        else:
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_ld_nodes(item)


def pick_text(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = normalize_text(value)
        return normalized or None
    if isinstance(value, list):
        for item in value:
            text = pick_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("name", "text"):
            if key in value:
                text = pick_text(value[key])
                if text:
                    return text
    return None


def product_from_json_ld(
    *,
    url: str,
    page_title: str | None,
    description: str | None,
    image_url: str | None,
    source_page_url: str,
    json_ld_nodes: list[dict[str, Any]],
    infer_match_type: Callable[[str | None, str | None, str | None, str | None], tuple[str, str, bool]],
) -> list[ProductRecord]:
    products: list[ProductRecord] = []
    breadcrumbs: list[str] = []
    for node in json_ld_nodes:
        node_type = node.get("@type")
        if node_type == "BreadcrumbList":
            for item in node.get("itemListElement", []):
                if isinstance(item, dict):
                    crumb = pick_text(item.get("name")) or pick_text(item.get("item"))
                    if crumb:
                        breadcrumbs.append(crumb)

    for node in json_ld_nodes:
        node_type = node.get("@type")
        types = {node_type} if isinstance(node_type, str) else set(node_type or [])
        if "Product" not in types:
            continue
        title = pick_text(node.get("name")) or page_title or slug_to_words(Path(urlparse(url).path).name)
        brand = pick_text(node.get("brand")) or None
        sku = pick_text(node.get("sku"))
        reference = pick_text(node.get("mpn")) or sku
        description_text = pick_text(node.get("description")) or description
        category_name = pick_text(node.get("category"))
        if not category_name and breadcrumbs:
            category_name = breadcrumbs[-2] if len(breadcrumbs) >= 2 else breadcrumbs[-1]
        subcategory_name = breadcrumbs[-1] if len(breadcrumbs) >= 2 else None
        record_image = pick_text(node.get("image")) or image_url
        vehicle_scope = "Autos" if "auto" in (description_text or "").lower() or "auto" in (category_name or "").lower() else None
        match_type, confidence, manual = infer_match_type(title, category_name, description_text, reference)
        products.append(
            ProductRecord(
                item_type="product",
                provider_type="product_catalog",
                product_name=title,
                product_url=url,
                detail_url=url,
                category_name=category_name,
                subcategory_name=subcategory_name,
                brand=brand,
                reference=reference,
                sku=sku,
                supplier_item_code=sku,
                description=description_text,
                vehicle_scope=vehicle_scope,
                image_url=record_image,
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
                    description_text,
                    reference,
                    sku,
                    vehicle_scope,
                ),
            )
        )
    return products


def extract_meta_content(html: str, property_name: str) -> str | None:
    patterns = [
        rf'<meta[^>]+property="{re.escape(property_name)}"[^>]+content="([^"]+)"',
        rf'<meta[^>]+name="{re.escape(property_name)}"[^>]+content="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return normalize_text(match.group(1))
    return None


def extract_page_title(html: str) -> str | None:
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if h1_match:
        title = normalize_text(h1_match.group(1))
        if title:
            return title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = normalize_text(title_match.group(1))
        title = re.sub(r"\s+[|\-–]\s+.*$", "", title)
        return title or None
    return None


def parse_product_fallback(
    *,
    url: str,
    html: str,
    source_page_url: str,
    category_only_mode: bool,
    infer_match_type: Callable[[str | None, str | None, str | None, str | None], tuple[str, str, bool]],
) -> ProductRecord | None:
    title = extract_page_title(html)
    if not title:
        return None
    description = extract_meta_content(html, "description")
    image_url = extract_meta_content(html, "og:image")
    brand = None
    brand_match = re.search(r"\bMarca[:\s]+([A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ\- ]{2,})", html, re.IGNORECASE)
    if brand_match:
        brand = normalize_text(brand_match.group(1))
    breadcrumb_parts = [
        normalize_text(value)
        for value in re.findall(r"<a[^>]+(?:breadcrumb|crumb)[^>]*>(.*?)</a>", html, re.IGNORECASE | re.DOTALL)
        if normalize_text(value)
    ]
    category_name = breadcrumb_parts[-2] if len(breadcrumb_parts) >= 2 else None
    subcategory_name = breadcrumb_parts[-1] if len(breadcrumb_parts) >= 1 else None
    slug_name = slug_to_words(Path(urlparse(url).path).name)
    reference = None
    ref_match = re.search(r"\b([A-Z0-9]{3,}(?:[-/][A-Z0-9]+)+)\b", slug_name.upper())
    if ref_match:
        reference = ref_match.group(1)
    vehicle_scope = "Autos" if "moto" not in title.lower() and "camion" not in title.lower() else None
    match_type, confidence, manual = infer_match_type(title, category_name, description, reference)
    return ProductRecord(
        item_type="product",
        provider_type="product_catalog" if not category_only_mode else "product_catalog_partial",
        product_name=title,
        product_url=url,
        detail_url=url,
        category_name=category_name,
        subcategory_name=subcategory_name,
        brand=brand,
        reference=reference,
        sku=reference,
        supplier_item_code=reference,
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
            vehicle_scope,
        ),
    )


def parse_category_record(
    *,
    url: str,
    html: str,
    source_page_url: str,
    exclude_keywords: Iterable[str],
    match_type: str = "category_only",
) -> ProductRecord | None:
    title = extract_page_title(html)
    if not title:
        return None
    lowered = title.lower()
    if ignored_by_keywords(title, exclude_keywords) or any(keyword in lowered for keyword in ("moto", "camion", "diesel")):
        return None
    description = extract_meta_content(html, "description")
    return ProductRecord(
        item_type="category",
        provider_type="category_only",
        title=title,
        detail_url=url,
        category_name=title,
        description=description,
        source_page_url=source_page_url,
        page_number=guess_page_number(source_page_url),
        match_type=match_type,
        match_confidence="medium" if match_type == "category_only" else "low",
        requires_manual_confirmation=True,
        searchable_tokens=build_searchable_tokens(title, description),
    )


def parse_pdf_records(html: str, base_url: str, source_page_url: str) -> list[ProductRecord]:
    records: list[ProductRecord] = []
    seen: set[str] = set()
    for match in re.finditer(
        r'<a\b([^>]*)href="([^"]+\.pdf(?:\?[^"]*)?)"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        _, href, body = match.groups()
        url = canonical_url(urljoin(base_url, unescape(href)))
        if url in seen:
            continue
        seen.add(url)
        label = normalize_text(body) or slug_to_words(Path(urlparse(url).path).stem)
        records.append(
            ProductRecord(
                item_type="document",
                provider_type="category_only",
                title=label,
                detail_url=url,
                category_name="Catalogo PDF",
                description="Documento PDF publico para verificacion manual.",
                source_page_url=source_page_url,
                page_number=guess_page_number(source_page_url),
                match_type="manual_confirmation_required",
                match_confidence="low",
                requires_manual_confirmation=True,
                searchable_tokens=build_searchable_tokens(label, "catalogo", "pdf"),
            )
        )
    return records


def previous_snapshot_file(output_dir: Path, snapshot_date: str) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(
        path / "extracted.json"
        for path in output_dir.iterdir()
        if path.is_dir() and path.name < snapshot_date and (path / "extracted.json").exists()
    )
    return candidates[-1] if candidates else None


def build_diff(current_products: list[ProductRecord], previous_snapshot_path: Path | None) -> dict[str, Any]:
    current_map = {
        record.detail_url or record.product_url or f"{record.item_type}:{record.title or record.product_name}": record
        for record in current_products
    }
    if not previous_snapshot_path or not previous_snapshot_path.exists():
        return {
            "previous_snapshot": None,
            "added_records": sorted(current_map),
            "removed_records": [],
            "changed_records": [],
        }

    previous_payload = load_json(previous_snapshot_path)
    previous_map = {
        record.get("detail_url") or record.get("product_url") or f"{record.get('item_type')}:{record.get('title') or record.get('product_name')}"
        : record
        for record in previous_payload.get("products", [])
        if isinstance(record, dict)
    }
    changed_records: list[dict[str, Any]] = []
    for key, record in current_map.items():
        old = previous_map.get(key)
        if not old:
            continue
        changes: dict[str, Any] = {}
        for field_name in ("title", "product_name", "category_name", "subcategory_name", "brand", "reference"):
            old_value = old.get(field_name)
            new_value = getattr(record, field_name, None)
            if old_value != new_value:
                changes[field_name] = {"old": old_value, "new": new_value}
        if changes:
            changed_records.append({"record_key": key, "changes": changes})
    return {
        "previous_snapshot": str(previous_snapshot_path),
        "added_records": sorted(key for key in current_map if key not in previous_map),
        "removed_records": sorted(key for key in previous_map if key not in current_map),
        "changed_records": changed_records,
    }


def write_csv(path: Path, products: list[ProductRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "item_type",
                "provider_type",
                "title",
                "product_name",
                "detail_url",
                "product_url",
                "category_name",
                "subcategory_name",
                "brand",
                "reference",
                "sku",
                "vehicle_scope",
                "match_type",
                "match_confidence",
            ],
        )
        writer.writeheader()
        for product in products:
            writer.writerow(
                {
                    "item_type": product.item_type,
                    "provider_type": product.provider_type,
                    "title": product.title,
                    "product_name": product.product_name,
                    "detail_url": product.detail_url,
                    "product_url": product.product_url,
                    "category_name": product.category_name,
                    "subcategory_name": product.subcategory_name,
                    "brand": product.brand,
                    "reference": product.reference,
                    "sku": product.sku,
                    "vehicle_scope": product.vehicle_scope,
                    "match_type": product.match_type,
                    "match_confidence": product.match_confidence,
                }
            )


def write_summary(path: Path, payload: dict[str, Any], diff: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    product_count = len(payload.get("products", []))
    lines = [
        f"# {payload.get('provider_name', payload.get('provider_id'))}",
        "",
        f"- Snapshot date: {payload.get('snapshot_date')}",
        f"- Records: {product_count}",
        f"- Added records: {len(diff.get('added_records', []))}",
        f"- Removed records: {len(diff.get('removed_records', []))}",
        f"- Changed records: {len(diff.get('changed_records', []))}",
        "",
    ]
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def build_payload(
    *,
    provider_id: str,
    provider_name: str,
    metadata: dict[str, Any],
    products: list[ProductRecord],
    notes: list[str],
    snapshot_date: str,
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "provider_name": provider_name,
        "snapshot_date": snapshot_date,
        "timezone": "America/Bogota",
        "website": metadata.get("website"),
        "catalog_root_url": metadata.get("catalog_root_url"),
        "extraction_mode": "live_seeded_public_catalog_refresh",
        "notes": list(dict.fromkeys(notes)),
        "products": [asdict(product) for product in products],
    }


def write_snapshot_bundle(
    *,
    output_root: Path,
    snapshot_date: str,
    payload: dict[str, Any],
    products: list[ProductRecord],
) -> Path:
    snapshot_dir = output_root / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    extracted_path = snapshot_dir / "extracted.json"
    csv_path = snapshot_dir / "products.csv"
    diff_path = snapshot_dir / "diff.json"
    summary_path = snapshot_dir / "summary.md"
    extracted_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(csv_path, products)
    diff = build_diff(products, previous_snapshot_file(output_root, snapshot_date))
    diff_path.write_text(json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary(summary_path, payload, diff)
    return extracted_path


def dedupe_records(records: Iterable[ProductRecord], exclude_keywords: Iterable[str]) -> list[ProductRecord]:
    deduped: dict[str, ProductRecord] = {}
    for record in records:
        text_value = record.detail_url or record.product_url or record.title or record.product_name or ""
        if ignored_by_keywords(text_value, exclude_keywords):
            continue
        if record.product_name and ignored_by_keywords(record.product_name, exclude_keywords):
            continue
        key = record.detail_url or record.product_url or f"{record.item_type}:{record.title or record.product_name}"
        if key not in deduped or len(record.searchable_tokens) > len(deduped[key].searchable_tokens):
            deduped[key] = record
    return list(deduped.values())
