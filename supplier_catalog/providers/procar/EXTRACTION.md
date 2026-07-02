# Procar Extraction Notes

Provider: `procar`

Website: `https://procar.com.co/`

Autos catalog roots:

- `https://procar.com.co/categoria-producto/llantas/`
- `https://procar.com.co/categoria-producto/llantas/auto/`
- `https://procar.com.co/categoria-producto/llantas/camioneta/`
- `https://procar.com.co/categoria-producto/filtros/`
- `https://procar.com.co/categoria-producto/lubricantes/`
- `https://procar.com.co/categoria-producto/otros-productos/`

Status: public site. A modal may appear on the home page, but the catalog pages are the operational source and should be treated as the main extraction surface.

## Why This Provider Matters

Procar is useful because it exposes an autos-oriented catalog with category pages and product detail pages that carry richer information than simple category-only suppliers.

The most relevant source pages for Orbika are:

- autos category pages
- product detail pages
- autos-focused product cards or listings

Ignore motos and heavy-duty lines. Keep `camioneta` in scope.

## Important Extraction Rule

Do not rely on the home modal as part of the extraction workflow unless it blocks access to the catalog. The catalog and product pages are the meaningful source of truth.

## Extraction Target

For each product or catalog entry, extract what is visible and reliable:

- `product_name`
- `product_url`
- `category_name`
- `subcategory_name`, when visible
- `brand`, when visible
- `description`, when visible
- `image_url`, when visible
- `image_alt`, when visible
- `price`, when visible
- `vehicle_scope`, when visible
- `page_number`
- `source_page_url`
- `searchable_tokens`
- `match_type`
- `match_confidence`
- `requires_manual_confirmation`

If a stable reference code or SKU appears publicly, capture it. If not, do not invent one.

## Matching Rule

Use this priority:

1. `vehicle_compatible` when the product detail clearly supports autos fitment or a compatible vehicle family.
2. `category_only` when only the family or category is clear.
3. `manual_confirmation_required` when the listing is too generic or incomplete.

Treat exact reference matching as possible only if a public reference is actually exposed on the catalog or detail page.

## Daily Snapshot Rule

Procar must be refreshed every day at `07:00` local time.

Each daily refresh should create:

```text
supplier_catalog/providers/procar/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/procar/snapshots/YYYY-MM-DD/products.csv
supplier_catalog/providers/procar/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/procar/snapshots/YYYY-MM-DD/summary.md
```

The snapshot should report:

- new products
- removed products
- changed detail URLs
- changed titles
- changed category paths
- pages that failed to render or paginate

## Adapter Notes

The adapter should remain read-only.

It must not:

- depend on the home modal
- add items to carts
- try to checkout
- login
- assume motos or heavy-duty pages are part of the autos corpus

The first implementation should walk the listed autos catalog surfaces and capture the detail page for each relevant product.
