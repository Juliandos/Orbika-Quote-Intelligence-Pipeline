# Autorecambios LTDA Extraction Notes

Provider: `autorecambiosltda`

Website: `https://autorecambiosltda.com`

Catalog root: `https://autorecambiosltda.com/repuestos-para-carros-y-camionetas/`

Status: public site. Seed snapshot created from the user-provided public category and product examples; live validation is still pending.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

Use the category pages and product detail pages as the extraction surface. The product pages are descriptive enough to verify a part with confidence.

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
