# Redpuestos Extraction Notes

Provider: `redpuestos`

Website: `https://www.imotriz.com/tienda/redpuestos/`

Catalog root: `https://www.imotriz.com/tienda/redpuestos/catalogo/page/results`

Status: public site. Seed snapshot created from the user-provided public catalog examples and filter surfaces; live validation is still pending.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

This store is filter-driven and the catalog results page is the operational source. Use the store embed and catalog filters as the extraction entry point.

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
