# Importadoras Asociadas Extraction Notes

Provider: `importadorasasociadas`

Website: `https://www.importadorasasociadas.com/`

Catalog root: `https://www.importadorasasociadas.com/`

Status: public site. Seed snapshot created from the user-provided public catalog examples and filter routes; live validation is still pending.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

This catalog is filter-heavy. Use category entry points, brand discovery and cluster routes as the main source surface.

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
