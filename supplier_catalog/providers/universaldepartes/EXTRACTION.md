# Universal de Partes Extraction Notes

Provider: `universaldepartes`

Website: `https://www.universaldepartes.co/`

Catalog root: `https://www.universaldepartes.co/category/all-products`

Status: public site. Live validation completed against the all-products listing with dynamic query pagination.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

Use the all-products category listing and exhaust query pagination dynamically until no new page links remain. The latest live snapshot captured hundreds of autos products and the public pages expose enough product detail to support partial verification.

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
