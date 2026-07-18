# Propartes Extraction Notes

Provider: `propartes`

Website: `https://propartes.com/`

Catalog root: `https://propartes.com/autos/`

Status: public site. The live extractor now follows the autos surfaces, query-paginated category pages, and product detail pages when the URL clearly looks like a product.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

Use the autos catalog and the query-paginated filtro pages as the extraction surface. Many entries are only basic tags, so capture fitment clues carefully.

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

## Operational note

The extractor must not treat catalog listing pages, CSS assets, or favicon URLs as products. Only nested detail URLs on `tienda.propartes.com` should be treated as product pages unless the HTML explicitly proves otherwise.
