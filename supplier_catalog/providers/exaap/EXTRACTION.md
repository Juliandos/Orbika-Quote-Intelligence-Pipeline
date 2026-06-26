# Exaap Extraction Notes

Provider: `exaap`

Website: `https://exaap.com/`

Catalog root: `https://exaap.com/`

Status: public site. Seed snapshot created from the user-provided public catalog examples; live validation is still pending.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

The public site only exposes general product information. Treat it as a weak catalog and use it mainly for manual verification.

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
