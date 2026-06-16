# Parrales Snapshot Summary - 2026-06-09

Initial supplier catalog assessment for Parrales.

## Why It Matters

Parrales is more useful than Impocali for direct matching because it exposes
individual product pages, prices, and in some cases exact technical identifiers
such as `MARCA`, `REF`, and `SKU`.

## Observed Strengths

- Public catalog root with filter taxonomy
- Paginated listing
- Individual product pages
- Current price and sale price visibility
- Exact reference-like tokens embedded in product names
- Structured brand/reference/SKU on at least some product pages

## Current Public Taxonomy

Top-level categories observed:

- Cables electricos
- Iluminacion
- Lujos y accesorios
- Miscelanea electrica
- Pitos
- Plumillas limpiaparabrisas
- Repuestos electricos
- Repuestos mecanicos

## Matching Implication

This provider can support true product-level comparison.

Expected match priority:

1. Exact reference
2. SKU
3. Reference token inside product name
4. Vehicle compatibility or technical attributes
5. Category fallback

## Daily Refresh Rule

This provider must be refreshed every day at `07:00` local time.

Expected outputs:

```text
supplier_catalog/providers/parrales/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/parrales/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/parrales/snapshots/YYYY-MM-DD/summary.md
```

## Next Step

Build the automated adapter to walk the full catalog and extract every product
individually.
