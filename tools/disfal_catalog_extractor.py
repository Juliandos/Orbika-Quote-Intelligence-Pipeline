#!/usr/bin/env python3
"""Read-only Disfal partial-verification extractor for public family and brand pages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


DISFAL_HOME_URL = "https://www.disfal.com/"
DISFAL_AMORTIGUADORES_URL = "https://www.disfal.com/services/amortiguadores/"
DEFAULT_OUTPUT_DIR = Path("supplier_catalog/providers/disfal/snapshots")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
PARTIAL_VERIFICATION_NOTE = (
    "Public page exposes family, brand, and commercial-line information only. "
    "Exact part confirmation still requires manual validation with the supplier."
)
SERVICE_TAXONOMY_MAP = {
    "amortiguadores": "suspension_steering",
    "suspension": "suspension_steering",
    "correas": "belts_tensioners",
    "mangueras": "hoses_fluids",
    "tensores-poleas": "belts_tensioners",
    "poleas": "belts_tensioners",
    "sistemas-de-escape": "exhaust",
    "bujias": "ignition_electrical",
    "bomba-de-combustible": "fuel_delivery",
    "liquido-de-frenos": "brake_fluids",
    "crucetas": "driveline",
}
KNOWN_BRAND_KEYWORDS = {
    "paxis": "PAXIS",
    "monroe": "MONROE",
    "facet": "FACET",
    "dayco": "DAYCO",
    "drb": "DONGIL (DRB)",
    "dongil": "DONGIL (DRB)",
    "walker": "WALKER",
    "champion": "CHAMPION",
    "moog": "MOOG",
    "rancho": "RANCHO",
}


@dataclass
class ServiceFamily:
    family_name: str
    family_slug: str
    family_url: str
    taxonomy_label: str
    source: str = "public_home_page"
    match_type: str = "category_only"
    requires_manual_confirmation: bool = True


@dataclass
class BrandLandingPage:
    brand_name: str
    brand_url: str
    source: str = "public_home_page"
    notes: str = PARTIAL_VERIFICATION_NOTE


@dataclass
class ServiceSeriesEntry:
    service_name: str
    service_url: str
    brand_name: str
    commercial_line: str | None
    series_label: str | None
    heading_text: str
    image_url: str | None
    taxonomy_label: str
    match_type: str = "category_only"
    match_confidence: str = "medium"
    requires_manual_confirmation: bool = True
    verification_note: str = PARTIAL_VERIFICATION_NOTE


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


def load_html(url: str, html_path: Path | None, user_agent: str) -> str:
    if html_path:
        return html_path.read_text(encoding="utf-8", errors="replace")
    return fetch_html(url, user_agent=user_agent)


def normalize_service_slug(url: str) -> str:
    path = re.sub(r"^https://www\.disfal\.com/services/", "", url)
    path = path.strip("/")
    if path.endswith("-colombia"):
        path = path[: -len("-colombia")]
    return path


def taxonomy_for_service_slug(slug: str) -> str:
    return SERVICE_TAXONOMY_MAP.get(slug, "manual_review")


def parse_service_family_links(html: str) -> list[ServiceFamily]:
    families: list[ServiceFamily] = []
    seen_slugs: set[str] = set()
    for url, label_html in re.findall(
        r'<a[^>]+href="(https://www\.disfal\.com/services/[^"]+/)"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        family_name = normalize_text(label_html)
        family_slug = normalize_service_slug(url)
        if not family_name or family_slug in seen_slugs:
            continue
        families.append(
            ServiceFamily(
                family_name=family_name,
                family_slug=family_slug,
                family_url=url,
                taxonomy_label=taxonomy_for_service_slug(family_slug),
            )
        )
        seen_slugs.add(family_slug)
    return families


def infer_brand_name(label: str, url: str) -> str | None:
    lowered = f"{label} {url}".lower()
    for keyword, brand_name in KNOWN_BRAND_KEYWORDS.items():
        if keyword in lowered:
            return brand_name
    return None


def parse_brand_landing_pages(html: str) -> list[BrandLandingPage]:
    brand_pages: list[BrandLandingPage] = []
    seen_urls: set[str] = set()
    for url, label_html in re.findall(
        r'<a[^>]+href="(https://www\.disfal\.com/[^"]+/)"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        label = normalize_text(label_html)
        brand_name = infer_brand_name(label, url)
        if not brand_name or url in seen_urls:
            continue
        brand_pages.append(BrandLandingPage(brand_name=brand_name, brand_url=url))
        seen_urls.add(url)
    return brand_pages


def split_h2_blocks(html: str) -> list[tuple[str, str]]:
    starts = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", html, re.IGNORECASE | re.DOTALL))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(starts):
        heading_html = match.group(0)
        start = match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        blocks.append((heading_html, html[start:end]))
    return blocks


def parse_series_heading(heading_text: str) -> tuple[str, str | None, str | None] | None:
    text = heading_text.strip()
    if not text or text.lower() == "amortiguadores":
        return None
    if "preguntas frecuentes" in text.lower():
        return None

    if text.upper() == "PAXIS":
        return ("PAXIS", None, None)

    if ":" in text:
        left, right = [part.strip() for part in text.split(":", 1)]
    else:
        left, right = text, None

    if left.upper().startswith("AMORTIGUADORES RANCHO"):
        return ("RANCHO", "AMORTIGUADORES RANCHO", right)

    if left.upper().startswith("MONROE "):
        return ("MONROE", left[len("MONROE ") :].strip(), right)

    brand_name = infer_brand_name(left, left)
    if brand_name:
        return (brand_name, left, right)
    return None


def parse_amortiguadores_series(html: str, service_url: str) -> list[ServiceSeriesEntry]:
    entries: list[ServiceSeriesEntry] = []
    service_name = "Amortiguadores"
    for heading_html, block in split_h2_blocks(html):
        heading_text = normalize_text(heading_html)
        parsed = parse_series_heading(heading_text)
        if not parsed:
            continue
        brand_name, commercial_line, series_label = parsed
        image_match = re.search(r"<img\b([^>]*)>", block, re.IGNORECASE | re.DOTALL)
        image_url = None
        if image_match:
            attrs = image_match.group(1)
            image_url = html_attr(attrs, "data-src") or html_attr(attrs, "src")
        entries.append(
            ServiceSeriesEntry(
                service_name=service_name,
                service_url=service_url,
                brand_name=brand_name,
                commercial_line=commercial_line,
                series_label=series_label,
                heading_text=heading_text,
                image_url=image_url,
                taxonomy_label="suspension_steering",
            )
        )
    return entries


def previous_snapshot_file(output_dir: Path, snapshot_date: str) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(
        path / "extracted.json"
        for path in output_dir.iterdir()
        if path.is_dir() and path.name < snapshot_date and (path / "extracted.json").exists()
    )
    return candidates[-1] if candidates else None


def build_diff(
    families: list[ServiceFamily],
    brand_pages: list[BrandLandingPage],
    service_series: list[ServiceSeriesEntry],
    previous_snapshot_path: Path | None,
) -> dict[str, Any]:
    if not previous_snapshot_path or not previous_snapshot_path.exists():
        return {
            "previous_snapshot": None,
            "added_family_urls": [record.family_url for record in families],
            "removed_family_urls": [],
            "added_brand_urls": [record.brand_url for record in brand_pages],
            "removed_brand_urls": [],
            "added_series_entries": [record.heading_text for record in service_series],
            "removed_series_entries": [],
        }

    previous_payload = json.loads(previous_snapshot_path.read_text(encoding="utf-8"))
    previous_family_urls = {
        record["family_url"] for record in previous_payload.get("service_families", []) if record.get("family_url")
    }
    previous_brand_urls = {
        record["brand_url"] for record in previous_payload.get("brand_pages", []) if record.get("brand_url")
    }
    previous_series_headings = {
        record["heading_text"] for record in previous_payload.get("service_series", []) if record.get("heading_text")
    }

    current_family_urls = {record.family_url for record in families}
    current_brand_urls = {record.brand_url for record in brand_pages}
    current_series_headings = {record.heading_text for record in service_series}

    return {
        "previous_snapshot": str(previous_snapshot_path),
        "added_family_urls": sorted(current_family_urls - previous_family_urls),
        "removed_family_urls": sorted(previous_family_urls - current_family_urls),
        "added_brand_urls": sorted(current_brand_urls - previous_brand_urls),
        "removed_brand_urls": sorted(previous_brand_urls - current_brand_urls),
        "added_series_entries": sorted(current_series_headings - previous_series_headings),
        "removed_series_entries": sorted(previous_series_headings - current_series_headings),
    }


def write_summary(path: Path, payload: dict[str, Any], diff: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Disfal Snapshot Summary - {payload['snapshot_date']}",
        "",
        "Verification scope: partial_verification_only",
        f"Service families extracted: {payload['summary']['service_families_extracted']}",
        f"Brand landing pages extracted: {payload['summary']['brand_pages_extracted']}",
        f"Service-series entries extracted: {payload['summary']['service_series_extracted']}",
        f"Added family URLs vs previous snapshot: {len(diff['added_family_urls'])}",
        f"Removed family URLs vs previous snapshot: {len(diff['removed_family_urls'])}",
        f"Added brand URLs vs previous snapshot: {len(diff['added_brand_urls'])}",
        f"Removed brand URLs vs previous snapshot: {len(diff['removed_brand_urls'])}",
        f"Added series entries vs previous snapshot: {len(diff['added_series_entries'])}",
        f"Removed series entries vs previous snapshot: {len(diff['removed_series_entries'])}",
        "",
        "Disfal remains a read-only partial verification supplier.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-date", default=str(date.today()))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--diff-output", type=Path, default=None)
    parser.add_argument("--home-html-path", type=Path, default=None)
    parser.add_argument("--amortiguadores-html-path", type=Path, default=None)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    snapshot_dir = args.output_root / args.snapshot_date
    json_output = args.json_output or snapshot_dir / "extracted.json"
    summary_output = args.summary_output or snapshot_dir / "summary.md"
    diff_output = args.diff_output or snapshot_dir / "diff.json"

    home_html = load_html(DISFAL_HOME_URL, args.home_html_path, args.user_agent)
    amortiguadores_html = load_html(
        DISFAL_AMORTIGUADORES_URL,
        args.amortiguadores_html_path,
        args.user_agent,
    )

    families = parse_service_family_links(home_html)
    brand_pages = parse_brand_landing_pages(home_html)
    service_series = parse_amortiguadores_series(amortiguadores_html, DISFAL_AMORTIGUADORES_URL)

    previous_snapshot = previous_snapshot_file(args.output_root, args.snapshot_date)
    diff = build_diff(families, brand_pages, service_series, previous_snapshot)

    payload = {
        "provider_id": "disfal",
        "provider_name": "Disfal",
        "snapshot_date": args.snapshot_date,
        "timezone": "America/Bogota",
        "verification_scope": "partial_verification_only",
        "website": DISFAL_HOME_URL,
        "reviewed_service_page": DISFAL_AMORTIGUADORES_URL,
        "service_families": [asdict(record) for record in families],
        "brand_pages": [asdict(record) for record in brand_pages],
        "service_series": [asdict(record) for record in service_series],
        "summary": {
            "service_families_extracted": len(families),
            "brand_pages_extracted": len(brand_pages),
            "service_series_extracted": len(service_series),
        },
    }

    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    diff_output.write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_summary(summary_output, payload, diff)

    print(
        f"Extracted {len(families)} Disfal family link(s), "
        f"{len(brand_pages)} brand page(s), and "
        f"{len(service_series)} service-series entry(ies). Output: {json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
