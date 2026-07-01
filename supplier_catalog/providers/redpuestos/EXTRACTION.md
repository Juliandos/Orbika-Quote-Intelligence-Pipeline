# Redpuestos Extraction Notes

Provider: `redpuestos`

Website: `https://www.imotriz.com/tienda/redpuestos/`

Catalog root: `https://www.imotriz.com/tienda/redpuestos/catalogo/page/results`

Status: public site. The live extractor now runs in browser mode and may require manual human validation if a captcha appears.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

This store is filter-driven and the catalog results page is the operational source. Use the rendered store embed and catalog filters as the extraction entry point.

## Live run

Use a visible browser when captcha support is needed:

```bash
REDPUESTOS_HEADED=1 REDPUESTOS_WAIT_FOR_HUMAN=1 uv run --with playwright python tools/redpuestos_catalog_extractor.py
```

## Extraction target

Capture only what is visible and reliable:

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
