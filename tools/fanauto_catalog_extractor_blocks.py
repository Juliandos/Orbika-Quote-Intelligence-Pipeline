from __future__ import annotations

import csv
import json
import re
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ID = "fanauto"
SNAPSHOT_DATE = "2026-07-06"
PROVIDER_DIR = ROOT / "supplier_catalog" / "providers" / PROVIDER_ID
SNAPSHOT_DIR = PROVIDER_DIR / "snapshots" / SNAPSHOT_DATE
EVIDENCE_DIR = SNAPSHOT_DIR / "evidence"
PAGES_DIR = EVIDENCE_DIR / "pages"
BLOCKS_DIR = EVIDENCE_DIR / "blocks"


@dataclass(frozen=True)
class CatalogPage:
    page_number: int
    image_url: str
    image_path: Path


def _ensure_dirs() -> None:
    for path in (SNAPSHOT_DIR, EVIDENCE_DIR, PAGES_DIR, BLOCKS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _download(url: str, destination: Path) -> None:
    if destination.exists():
        return
    with urllib.request.urlopen(url) as response, destination.open("wb") as fh:
        shutil.copyfileobj(response, fh)


def _load_pages() -> list[CatalogPage]:
    pages_json = SNAPSHOT_DIR / "catalog_pages.json"
    candidates: list[dict] = []

    if pages_json.exists():
        data = json.loads(pages_json.read_text(encoding="utf-8"))
        if isinstance(data, list):
            candidates = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            for key in ("pages", "catalog_pages", "page_images", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    candidates = [item for item in value if isinstance(item, dict)]
                    if candidates:
                        break

    pages: list[CatalogPage] = []
    if candidates:
        for item in candidates:
            page_number = int(item.get("page_number") or item.get("page") or item.get("index") or len(pages) + 1)
            image_url = item.get("image_url") or item.get("url") or item.get("image") or ""
            image_path = PAGES_DIR / f"{page_number:03d}.jpg"
            if image_url:
                _download(image_url, image_path)
            pages.append(CatalogPage(page_number, image_url, image_path))
        return sorted(pages, key=lambda page: page.page_number)

    image_files = sorted(PAGES_DIR.glob("*.jpg")) + sorted(PAGES_DIR.glob("*.jpeg")) + sorted(PAGES_DIR.glob("*.png"))
    if not image_files:
        raise SystemExit("No hay imágenes de páginas de Fanauto en evidence/pages.")
    for idx, image_path in enumerate(image_files, start=1):
        pages.append(CatalogPage(idx, "", image_path))
    return pages


def _ocr_reader():
    try:
        import easyocr
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Fanauto requiere easyocr. Ejecuta: uv run --with easyocr python tools/fanauto_catalog_extractor_blocks.py"
        ) from exc
    return easyocr.Reader(["es", "en"], gpu=False)


def _ocr_lines(reader, image_path: Path) -> list[str]:
    result = reader.readtext(str(image_path), detail=0, paragraph=False)
    lines: list[str] = []
    for item in result:
        text = re.sub(r"\s+", " ", str(item)).strip()
        if text:
            lines.append(text)
    return lines


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\W_]+|[\W_]+$", "", text)
    return text


def _looks_like_noise(text: str) -> bool:
    lowered = text.lower()
    if not text:
        return True
    if len(text) < 4:
        return True
    noise_tokens = {
        "fanauto",
        "jafs",
        "catalogo",
        "catálogo",
        "pagina",
        "página",
        "suspension",
        "frenos",
        "motos",
        "contacto",
        "inicio",
        "valores",
    }
    if lowered in noise_tokens:
        return True
    if sum(ch.isalpha() for ch in text) < 4:
        return True
    return False


def _split_page_boxes(page_image: Path) -> list[tuple[int, int, int, int]]:
    image = Image.open(page_image).convert("RGB")
    width, height = image.size

    left_margin = int(width * 0.02)
    right_margin = int(width * 0.02)
    top_margin = int(height * 0.11)
    bottom_margin = int(height * 0.07)
    center_gap = int(width * 0.018)
    row_gap = int(height * 0.015)

    usable_left = left_margin
    usable_right = width - right_margin
    usable_top = top_margin
    usable_bottom = height - bottom_margin
    spread_width = usable_right - usable_left

    half_width = (spread_width - center_gap) // 2
    col_width = (half_width - 2 * center_gap) // 3
    row_height = (usable_bottom - usable_top - 3 * row_gap) // 4

    boxes: list[tuple[int, int, int, int]] = []
    for half_index in range(2):
        half_left = usable_left + half_index * (half_width + center_gap)
        for row_index in range(4):
            for col_index in range(3):
                x1 = half_left + col_index * col_width
                y1 = usable_top + row_index * (row_height + row_gap)
                x2 = x1 + col_width
                y2 = y1 + row_height
                pad_x = int(col_width * 0.04)
                pad_y = int(row_height * 0.05)
                boxes.append((max(0, x1 + pad_x), max(0, y1 + pad_y), min(width, x2 - pad_x), min(height, y2 - pad_y)))
    return boxes


def _crop_and_save(image: Image.Image, bbox: tuple[int, int, int, int], path: Path) -> Path:
    crop = image.crop(bbox)
    crop.save(path)
    return path


def _first_meaningful_line(lines: list[str]) -> str:
    for line in lines:
        cleaned = _clean_text(line)
        if cleaned and not _looks_like_noise(cleaned):
            return cleaned
    return ""


def _join_title_lines(lines: list[str]) -> str:
    candidates: list[str] = []
    for line in lines[:4]:
        cleaned = _clean_text(line)
        if not cleaned or _looks_like_noise(cleaned):
            continue
        if len(cleaned) > 90:
            continue
        candidates.append(cleaned)
        if len(candidates) == 2:
            break
    if not candidates:
        return ""
    title = " ".join(candidates)
    title = re.sub(r"\s{2,}", " ", title).strip(" -")
    return title


def _description_lines(lines: list[str], title: str) -> str:
    cleaned_lines: list[str] = []
    for line in lines:
        cleaned = _clean_text(line)
        if not cleaned or _looks_like_noise(cleaned):
            continue
        if title and cleaned == title:
            continue
        if cleaned in cleaned_lines:
            continue
        cleaned_lines.append(cleaned)
    if not cleaned_lines:
        return ""
    return " ".join(cleaned_lines[:5]).strip()


def _product_record(page: CatalogPage, block_index: int, bbox: tuple[int, int, int, int], title: str, description: str) -> dict:
    base = {
        "provider_id": PROVIDER_ID,
        "source_page_number": page.page_number,
        "source_page_image": str(page.image_path.relative_to(SNAPSHOT_DIR)).replace("\\", "/"),
        "source_block_index": block_index,
        "source_block_bbox": list(bbox),
        "match_status": "manual_confirmation_required",
        "category": "catalogo-digital",
        "url": "https://fanauto.com.co/catalogo-digital/",
    }
    name = title or description[:120]
    return {
        **base,
        "name": name,
        "description": description or title,
    }


def _extract_page(reader, page: CatalogPage) -> list[dict]:
    if page.page_number in {1, 102}:
        return []

    image = Image.open(page.image_path).convert("RGB")
    boxes = _split_page_boxes(page.image_path)
    records: list[dict] = []

    for block_index, bbox in enumerate(boxes, start=1):
        block_path = BLOCKS_DIR / f"page-{page.page_number:03d}-block-{block_index:02d}.png"
        _crop_and_save(image, bbox, block_path)

        x1, y1, x2, y2 = bbox
        height = y2 - y1
        title_bbox = (x1, y1, x2, y1 + int(height * 0.22))
        desc_bbox = (x1, y1 + int(height * 0.60), x2, y2)

        title_path = BLOCKS_DIR / f"page-{page.page_number:03d}-block-{block_index:02d}-title.png"
        desc_path = BLOCKS_DIR / f"page-{page.page_number:03d}-block-{block_index:02d}-desc.png"
        _crop_and_save(image, title_bbox, title_path)
        _crop_and_save(image, desc_bbox, desc_path)

        title_lines = _ocr_lines(reader, title_path)
        desc_lines = _ocr_lines(reader, desc_path)
        full_lines = _ocr_lines(reader, block_path)

        title = _join_title_lines(title_lines) or _join_title_lines(full_lines[:3]) or _first_meaningful_line(full_lines[:2])
        description = _description_lines(desc_lines, title)

        if not title:
            title = _first_meaningful_line(full_lines[:3])
        if not description:
            description = _description_lines(full_lines[2:8], title)

        if not description and not title:
            continue
        if not title and description:
            title = description[:120]
        if not description and title:
            description = title

        if len(title) < 4 and len(description) < 8:
            continue
        if title.isdigit() and len(description) < 12:
            continue
        if title in {"---", "..."} and len(description) < 12:
            continue

        records.append(_product_record(page, block_index, bbox, title, description))

    return records


def crawl_provider() -> dict:
    _ensure_dirs()
    reader = _ocr_reader()
    pages = _load_pages()

    records: list[dict] = []
    page_summaries: list[dict] = []
    for page in pages:
        page_records = _extract_page(reader, page)
        records.extend(page_records)
        page_summaries.append(
            {
                "page_number": page.page_number,
                "image_url": page.image_url,
                "record_count": len(page_records),
                "is_cover": page.page_number in {1, 102},
            }
        )

    payload = {
        "provider_id": PROVIDER_ID,
        "page_count": len(pages),
        "records": records,
        "pages": page_summaries,
        "catalog_surface": "flipbook image pages segmented into visual product cards",
    }

    (SNAPSHOT_DIR / "catalog_pages.json").write_text(json.dumps({"pages": page_summaries}, indent=2, ensure_ascii=False), encoding="utf-8")
    (SNAPSHOT_DIR / "extracted.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    with (SNAPSHOT_DIR / "products.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["name", "description", "source_page_number", "source_block_index", "source_page_image", "match_status"],
        )
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in writer.fieldnames})

    summary = [
        f"# Fanauto {SNAPSHOT_DATE}",
        "",
        f"- páginas procesadas: {len(pages)}",
        f"- productos detectados: {len(records)}",
        "- páginas 1 y 102 tratadas como portada/cierre",
        "- cada producto se construye por bloque visual independiente",
    ]
    (SNAPSHOT_DIR / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    return payload


def main() -> int:
    payload = crawl_provider()
    print(
        json.dumps(
            {
                "provider_id": payload["provider_id"],
                "snapshot_path": str(SNAPSHOT_DIR / "extracted.json").replace("\\", "/"),
                "records": len(payload["records"]),
                "page_count": payload["page_count"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
