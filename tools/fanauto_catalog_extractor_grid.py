from __future__ import annotations

import csv
import dataclasses
import json
import math
import re
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Fanauto extractor requiere Pillow. Ejecuta: uv run --with easyocr python tools/fanauto_catalog_extractor_grid.py"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ID = "fanauto"
PROVIDER_DIR = ROOT / "supplier_catalog" / "providers" / PROVIDER_ID
SNAPSHOT_DATE = "2026-07-06"
SNAPSHOT_DIR = PROVIDER_DIR / "snapshots" / SNAPSHOT_DATE
EVIDENCE_DIR = SNAPSHOT_DIR / "evidence"
PAGES_DIR = EVIDENCE_DIR / "pages"
BLOCKS_DIR = EVIDENCE_DIR / "blocks"

CATALOG_URL = "https://fanauto.com.co/catalogo-digital/"


@dataclass(frozen=True)
class PageImage:
    page_number: int
    image_url: str
    image_path: Path


@dataclass(frozen=True)
class Block:
    page_number: int
    block_number: int
    crop_path: Path
    bbox: tuple[int, int, int, int]
    text: str


def _ensure_dirs() -> None:
    for path in [SNAPSHOT_DIR, EVIDENCE_DIR, PAGES_DIR, BLOCKS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-")


def _download(url: str, destination: Path) -> None:
    if destination.exists():
        return
    with urllib.request.urlopen(url) as response, destination.open("wb") as fh:
        shutil.copyfileobj(response, fh)


def _load_flipbook_pages() -> list[PageImage]:
    """Reads existing flipbook evidence or rebuilds a minimal page list from local artefacts.

    The current Fanauto catalog is delivered as a 102-page flipbook; pages 1 and 102 are
    cover/back matter and do not contain products.
    """

    pages_json = SNAPSHOT_DIR / "catalog_pages.json"
    if pages_json.exists():
        data = json.loads(pages_json.read_text(encoding="utf-8"))
        pages: list[PageImage] = []
        page_items = []
        if isinstance(data, list):
            page_items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            for key in ("pages", "catalog_pages", "page_images", "items"):
                value = data.get(key)
                if isinstance(value, list) and value:
                    page_items = [item for item in value if isinstance(item, dict)]
                    break
        for item in page_items:
            page_number = int(item.get("page_number") or item.get("page") or item.get("index") or len(pages) + 1)
            image_url = item.get("image_url") or item.get("url") or item.get("image") or ""
            image_path = PAGES_DIR / f"{page_number:03d}.jpg"
            if not image_path.exists() and image_url:
                _download(image_url, image_path)
            pages.append(PageImage(page_number, image_url, image_path))
        if pages:
            return pages
    raise SystemExit(
        "No encontrÃ© catalog_pages.json para Fanauto. Ejecuta primero el extractor base para poblar la evidencia."
    )


def _ocr_engine():
    try:
        import easyocr
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Fanauto grid extractor requiere easyocr. Usa: uv run --with easyocr python tools/fanauto_catalog_extractor_grid.py"
        ) from exc
    return easyocr.Reader(["es", "en"], gpu=False)


def _ocr_image(reader, image_path: Path) -> str:
    result = reader.readtext(str(image_path), detail=0, paragraph=True)
    text = "\n".join(line.strip() for line in result if line and line.strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_grid(page_image: Path) -> list[tuple[int, int, int, int]]:
    """Split one flipbook page image into 12 blocks.

    The visible catalog spreads are consistent: 2 halves x 3 columns x 2 rows.
    We keep generous margins so the OCR can read titles and descriptions without
    bleeding into neighboring cards.
    """

    image = Image.open(page_image).convert("RGB")
    width, height = image.size

    top_margin = int(height * 0.20)
    bottom_margin = int(height * 0.12)
    left_margin = int(width * 0.04)
    right_margin = int(width * 0.04)
    gutter_x = int(width * 0.02)
    gutter_y = int(height * 0.03)

    content_top = top_margin
    content_bottom = height - bottom_margin
    content_left = left_margin
    content_right = width - right_margin

    half_width = (content_right - content_left - gutter_x) // 2
    half_height = content_bottom - content_top
    col_width = (half_width - 2 * gutter_x) // 3
    row_height = (half_height - gutter_y) // 2

    boxes: list[tuple[int, int, int, int]] = []
    for half_index in range(2):
        half_left = content_left + half_index * (half_width + gutter_x)
        for row_index in range(2):
            for col_index in range(3):
                x1 = half_left + col_index * col_width
                y1 = content_top + row_index * row_height
                x2 = x1 + col_width
                y2 = y1 + row_height
                pad_x = int(col_width * 0.08)
                pad_y = int(row_height * 0.05)
                boxes.append(
                    (
                        max(0, x1 + pad_x),
                        max(0, y1 + pad_y),
                        min(width, x2 - pad_x),
                        min(height, y2 - pad_y),
                    )
                )
    return boxes


def _product_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\W_]+|[\W_]+$", "", text)
    return text


def _looks_like_product(text: str) -> bool:
    lowered = text.lower()
    if len(text) < 12:
        return False
    if lowered in {"fanauto", "catÃ¡logo", "catalogo"}:
        return False
    if sum(ch.isalpha() for ch in text) < 8:
        return False
    return True


def _crop_blocks(page_number: int, image_path: Path, reader) -> list[Block]:
    boxes = _split_grid(image_path)
    image = Image.open(image_path).convert("RGB")
    blocks: list[Block] = []
    for idx, bbox in enumerate(boxes, start=1):
        crop = image.crop(bbox)
        crop_path = BLOCKS_DIR / f"page-{page_number:03d}-block-{idx:02d}.png"
        crop.save(crop_path)
        text = _product_text(_ocr_image(reader, crop_path))
        if _looks_like_product(text):
            blocks.append(Block(page_number, idx, crop_path, bbox, text))
    return blocks


def _fallback_record(page_number: int, text: str, source_image: Path) -> dict:
    return {
        "provider_id": PROVIDER_ID,
        "name": text[:180],
        "description": text,
        "source_page_number": page_number,
        "source_page_image": str(source_image.relative_to(SNAPSHOT_DIR)).replace("\\", "/"),
        "source_type": "flipbook_ocr_block",
        "match_status": "manual_confirmation_required",
        "category": "fanauto/catalogo-digital",
        "url": CATALOG_URL,
    }


def crawl_provider() -> dict:
    _ensure_dirs()
    pages = _load_flipbook_pages()
    reader = _ocr_engine()

    records: list[dict] = []
    page_summaries: list[dict] = []

    for page in pages:
        if page.page_number in {1, 102}:
            page_summaries.append(
                {
                    "page_number": page.page_number,
                    "image_url": page.image_url,
                    "product_count": 0,
                    "notes": "front/back matter",
                }
            )
            continue

        blocks = _crop_blocks(page.page_number, page.image_path, reader)
        page_summaries.append(
            {
                "page_number": page.page_number,
                "image_url": page.image_url,
                "product_count": len(blocks),
                "notes": "grid_ocr",
            }
        )
        for block in blocks:
            records.append(_fallback_record(block.page_number, block.text, page.image_path))

    payload = {
        "provider_id": PROVIDER_ID,
        "catalog_surface": "flipbook image pages segmented into product blocks",
        "page_count": len(pages),
        "records": records,
        "pages": page_summaries,
    }

    (SNAPSHOT_DIR / "catalog_pages.json").write_text(
        json.dumps({"provider_id": PROVIDER_ID, "pages": page_summaries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (SNAPSHOT_DIR / "extracted.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    with (SNAPSHOT_DIR / "products.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["name", "description", "source_page_number", "source_page_image", "match_status"],
        )
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in writer.fieldnames})

    summary = [
        f"# Fanauto {SNAPSHOT_DATE}",
        "",
        f"- pÃ¡ginas procesadas: {len(pages)}",
        f"- productos OCR detectados: {len(records)}",
        "- pÃ¡ginas 1 y 102 tratadas como portada/cierre",
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
                "pages": payload["page_count"],
                "records": len(payload["records"]),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

