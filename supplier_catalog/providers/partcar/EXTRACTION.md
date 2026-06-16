# Partcar Extraction Notes

Provider: `partcar`

Website: `https://www.partcar.com.co/`

Catalog page reviewed: `https://www.partcar.com.co/importacion-1`

Status: open website, no login required.

## Why This Provider Matters

Partcar exposes a public paginated catalog of individual autoparts with:

- visible product title
- visible supplier-side code
- product image
- public product detail link

Unlike category-only suppliers, this source exposes product-level cards. That
makes it useful for name-based matching and manual verification.

## Important Limitation

The visible numeric code in the card appears to be a supplier catalog code, not
an OEM/reference code proven to be compatible with Orbika references.

For this reason:

- store it as `supplier_item_code`
- do not automatically promote it to `exact_reference`
- require manual confirmation unless a later rule proves that the code matches a
  stable external reference system

## Pagination Rule

Although the browser UI shows a next button, the public page also exposes
stable pagination using:

```text
https://www.partcar.com.co/importacion-1?dynamic_page=N
```

The adapter should prefer this public URL pattern over browser clicking because
it is simpler and more robust.

The user-provided selector:

```css
#comp-mlpnn4l8 > button > span
```

should be preserved as a UI note only, not as the primary extraction strategy.

## Extraction Target

For each visible product card, extract:

- `product_name`
- `supplier_item_code`
- `detail_url`
- `image_url`
- `image_alt`
- `page_number`
- `source_page_url`
- `taxonomy_label`
- `searchable_tokens`
- `match_type`
- `match_confidence`
- `requires_manual_confirmation`

## Matching Rule

Use this priority:

1. `category_only` when the product title clearly identifies the commercial part
   family.
2. `manual_confirmation_required` when the product title is too ambiguous.
3. Never mark the Partcar visible code as `exact_reference` by default.

## Classification Rule

Partcar item titles should feed the shared autoparts taxonomy.

Examples:

- `Farola` -> `lighting_headlamps`
- `Stop` -> `lighting_tail_lamps`
- `Espejo` -> `mirrors`
- `Parachoque` or `Bumper` -> `body_exterior`
- `Capo` -> `body_exterior`
- `Guardafango` -> `body_exterior`
- `Rejilla` -> `front_grille`

Preserve the original title and store the normalized taxonomy separately.

## Daily Snapshot Rule

Partcar must be refreshed every day at `07:00` local time.

Each daily refresh should create:

```text
supplier_catalog/providers/partcar/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/partcar/snapshots/YYYY-MM-DD/products.csv
supplier_catalog/providers/partcar/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/partcar/snapshots/YYYY-MM-DD/summary.md
```

The snapshot should compare against the previous available day and report:

- new product URLs
- removed product URLs
- changed visible codes
- changed visible titles
- pagination failures

## Adapter Notes

The adapter must remain read-only.

It must not:

- login
- add items to carts
- use WhatsApp actions
- submit searches or forms unless strictly needed in a future controlled step

The first implementation should use public HTTP extraction, following
`dynamic_page` pagination until there is no `rel="next"` link or no new
products appear.
