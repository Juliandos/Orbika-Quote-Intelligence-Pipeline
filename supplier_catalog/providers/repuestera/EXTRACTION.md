# Repuestera Extraction Notes

Provider: `repuestera`

Website: `https://repuestera.com.co/`

Catalog root: `https://repuestera.com.co/shop/`

Status: open website, no login required.

## Why This Provider Matters

Repuestera exposes a public product catalog with individual product cards and
public detail links.

Visible product card data includes:

- reference code
- commercial product name
- brand
- commercial category
- product image
- public product detail URL

This makes Repuestera stronger than category-only suppliers because the visible
reference can be compared directly against extracted quote references.

## Relevant Public Areas

Two public areas are relevant on the shop page:

1. A category carousel near the top, which acts as a high-level taxonomy entry.
2. A paginated product listing below the filters, where each product card
   exposes the initial commercial information we need.

## Extraction Target

For the category carousel, extract:

- `category_name`
- `category_url`
- `image_url`

For each visible product card, extract:

- `post_id`
- `reference`
- `product_name`
- `brand`
- `category_name`
- `detail_url`
- `image_url`
- `image_alt`
- `page_number`
- `source_page_url`
- `searchable_tokens`
- `match_type`
- `match_confidence`

## Matching Rule

Use this priority:

1. `exact_reference` when the card exposes a direct reference code.
2. `category_only` when only a product family is available.
3. `manual_confirmation_required` when the visible data is incomplete.

Because this source already exposes part references publicly, it is a strong
candidate for automated comparison against extracted quote items.

## Known Public Signals

Observed public listing structure includes:

- category carousel widget: `jet-woo-categories`
- category title links: `jet-woo-category-title__link`
- product grid widget id: `productos`
- product cards: `jet-listing-grid__item`
- product detail button text: `Ver detalles`
- product text search placeholder: `Busca un producto...`
- product reference search placeholder: `Buscar referencia...`

## Daily Snapshot Rule

Repuestera must be refreshed every day at `07:00` local time.

Each daily refresh should create:

```text
supplier_catalog/providers/repuestera/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/repuestera/snapshots/YYYY-MM-DD/products.csv
supplier_catalog/providers/repuestera/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/repuestera/snapshots/YYYY-MM-DD/summary.md
```

## Adapter Notes

The adapter should:

1. Read the public category carousel.
2. Detect the maximum number of catalog pages.
3. Walk every public shop page.
4. Extract the visible card information for every product.
5. Stay read-only and avoid cart, checkout, login, or customer portal actions.
