# Impocali Extraction Notes

Provider: `impocali`

Website: `https://impocali.com/`

Status: open website, no login required.

## Important Limitation

Impocali should be treated as a category-level supplier catalog, not as an exact
reference source.

The visible pages reviewed so far expose product families and names, but they do
not expose exact OEM/reference codes, stock, prices, or vehicle compatibility.

For this reason, Impocali matches must be marked as:

```text
category_only
manual_confirmation_required
```

Recommended business action:

```text
Call or contact Impocali to confirm exact reference, stock, compatibility, and price.
```

## Relevant Pages

Only these two product segments are relevant for now:

- Autos: `https://impocali.com/productos_impocali/autos/`
- Carga y pasajeros: `https://impocali.com/productos_impocali/carga-y-pasajeros/`

The `Motos` segment is intentionally ignored.

## User-Provided Selector

Primary product container selector:

```css
#main > section > div > div.post-product > div:nth-child(2) > div > div > div
```

This selector should be treated as a starting point, not the only allowed
selector. The adapter should also support resilient fallback selectors because
the page may change.

## Extraction Target

For each relevant segment, extract:

- `provider_id`: `impocali`
- `segment`: `autos` or `carga_y_pasajeros`
- `category_name`
- `category_url`
- `product_name`
- `product_url`, when visible
- `image_url`, when visible
- `brands`, when visible
- `source_url`
- `match_type`: `category_only`
- `requires_manual_confirmation`: `true`
- `notes`

## Brand Extraction Rule

Impocali sometimes displays brand information as logos inside the product card
image area instead of structured HTML text.

Brand extraction must follow this priority order:

1. Structured HTML attributes such as visible text, `alt`, `title`, `aria-label`,
   or image file names.
2. Brand image URLs or asset file names.
3. OCR/visual logo recognition only as a fallback.

Every detected brand must preserve provenance and confidence, for example:

```json
{
  "name": "Febi Bilstein",
  "source": "image",
  "confidence": "high"
}
```

If a brand is inferred visually and not confirmed from HTML, it must never be
stored as guaranteed truth. Keep the confidence level explicit.

## Classification Rule

Impocali data should feed the global autoparts taxonomy.

Examples:

- `Suspensión y Dirección` -> `suspension_steering`
- `Refrigeración` -> `cooling`
- `Filtración` -> `filters`
- `Lubricación` -> `lubricants_fluids`
- `Amortiguadores` -> `suspension_steering`
- `Rótulas` -> `suspension_steering`
- `Terminales` -> `suspension_steering`

The classifier must preserve the original visible text and add the normalized
taxonomy label separately.

## Daily Snapshot Rule

Impocali must be refreshed every day at `07:00` local time.

Each daily refresh should create:

```text
supplier_catalog/providers/impocali/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/impocali/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/impocali/snapshots/YYYY-MM-DD/summary.md
```

The snapshot should compare against the previous available date and report:

- New categories or names.
- Removed categories or names.
- Changed URLs.
- Selector failures.
- Empty or incomplete pages.

## Matching Against Orbika

Impocali should be compared against Orbika quote items by normalized family/type,
not by reference.

Example:

```text
Orbika item:
  reference: 664003W001
  visible_name: Capo
  inferred_taxonomy: body_exterior

Impocali:
  visible_name: Suspensión y Dirección
  taxonomy: suspension_steering

Result:
  no category match
```

Example:

```text
Orbika item:
  visible_name: Rodamiento delantero derecho
  inferred_taxonomy: suspension_steering

Impocali:
  visible_name: Suspensión y Dirección
  taxonomy: suspension_steering

Result:
  category_only candidate
  requires_manual_confirmation: true
```

## Adapter Notes

The adapter should not submit forms, place orders, login, or modify anything on
the supplier website.

The first implementation can use read-only HTTP/HTML extraction. Browser
automation should only be added if static extraction is not enough.
