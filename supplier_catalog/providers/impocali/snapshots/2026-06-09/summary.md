# Impocali Snapshot Summary - 2026-06-09

Initial supplier catalog snapshot for Impocali.

## Scope

Included segments:

- Autos
- Carga y pasajeros

Excluded segment:

- Motos

## Result

The snapshot captures public category and product-family names only.

Impocali does not expose exact references, stock, prices, or vehicle
compatibility on the reviewed public pages. Every result must be treated as:

```text
category_only
manual_confirmation_required
```

## Counts

- Segments included: 2
- Category records: 15
- Flat product names captured: 89
- Image-derived brand detections captured for selected visible product cards

## Important Notes

- Impocali can help decide whether a supplier may handle a broad family such as suspension, cooling, filters, lubrication, lighting, electrical, brakes, hydraulics, or engine parts.
- Impocali cannot prove that a specific Orbika reference is available.
- Carga y pasajeros showed a duplicated public listing for `Partes para motor`.
- The Autos detail URL for `Partes para motor` was not reliably available from the same domain during the initial review, so the public `web.impocali.com` mirror was used for the first snapshot.
- Some product cards also show brand logos. These were captured as image-derived brands with explicit confidence instead of being treated as structured text.

## Daily Refresh Rule

This provider must be refreshed every day at `07:00` local time.

The automated refresh should write:

```textshubumi
supplier_catalog/providers/impocali/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/impocali/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/impocali/snapshots/YYYY-MM-DD/summary.md
```

## Next Step

Implement the Impocali adapter so this snapshot can be generated automatically
and compared against the previous day.
