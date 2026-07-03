# Autopartesya Extraction Notes

Provider: `autopartesya`

Website: `https://www.autopartesya.co/`

Catalog root: `https://www.autopartesya.co/shop-2/`

Status: live browser-assisted validation complete for the catalog surface. The rendered DOM exposes product links even when raw HTML fetches stay empty.

Scope: autos only. Ignore motos, carga pesada, buses and camiones.

## What changed

- The listing crawl must use a browser session.
- Product detail links are discovered from the rendered DOM with `a[href*="/product/"]`.
- Pagination is dynamic and was discovered from the rendered pager, with a last page link around `140` during validation.
- Product detail pages expose usable JSON-LD, so reference codes, descriptions, images and prices can be enriched without inventing data.

## Extraction target

Capture only what is visible and reliable:

- `product_name` or `title`
- `product_url` or `detail_url`
- `category_name` / `subcategory_name`
- `brand`
- `reference`
- `sku`
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

This shop is still dense, but it is now suitable for a full live crawl. Keep it browser-based, reuse a single browser session, and let pagination drive the inventory instead of a fixed page limit.
