# Fanauto Extraction Notes

Provider: `fanauto`

Website: `https://fanauto.com.co/`

Catalog root: `https://fanauto.com.co/catalogo-digital/`

Status: public site. The catalog is a real3d flipbook made of 102 image pages.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

## Current approach

The extractor now treats the flipbook as a page-image catalog:

1. Download the 102 page images embedded in the flipbook options.
2. Store the page images as evidence under the snapshot folder.
3. OCR every page when OCR support is available in the runtime.
4. Emit page-level records and OCR text so the snapshot is useful even when the catalog is image-only.

## What to capture

Capture only what is visible and reliable from each page:

- `product_name` or `title`
- `product_url` or `detail_url`
- `category_name` / `subcategory_name`
- `brand`
- `description`
- `image_url` / `image_alt`
- `price` / `stock` when visible
- `vehicle_scope` when visible
- `page_number`
- `source_page_url`
- `searchable_tokens`
- `match_type`
- `match_confidence`
- `requires_manual_confirmation`

If a public reference code appears, capture it. If not, do not invent one.

## Evidence produced

Each snapshot should include:

- `extracted.json`
- `products.csv`
- `diff.json`
- `summary.md`
- `catalog_pages.json`
- `evidence/pages/*.jpg`
- `evidence/pages/*.txt` when OCR text is available
