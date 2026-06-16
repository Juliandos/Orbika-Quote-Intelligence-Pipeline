# Supplier Catalog Extraction

This directory contains the supplier catalog extraction project.

The goal is to build one adapter per supplier, normalize the extracted catalog
information, and compare it with successful Orbika quote extractions.

## Global Provider Rule

Every supplier must have its own provider folder and extraction document before
automation is added.

Required provider files:

- `EXTRACTION.md`: human-readable extraction notes, selectors, limitations, and matching rules.
- `provider.json`: machine-readable provider metadata, URLs, selectors, and snapshot policy.

## Daily Refresh Rule

Every active provider must be read again once per day at `07:00` local time.

The daily refresh must generate a dated extraction snapshot so changes can be
compared over time.

The daily snapshot should answer:

- Which categories or products were added?
- Which categories or products disappeared?
- Which URLs or selectors stopped working?
- Did the supplier expose more precise data than before?

## Matching Philosophy

Supplier matches must be honest about certainty.

Use these match levels:

- `exact_reference`: the supplier exposes the same reference/OEM code.
- `vehicle_compatible`: the supplier exposes vehicle compatibility data.
- `category_only`: the supplier only shows a product family or commercial category.
- `manual_confirmation_required`: the supplier may be relevant, but a call or manual check is needed.

Never mark a supplier as an exact match when the catalog only provides category
names.

## Planned Runtime Output

Daily generated files should be written under a dated snapshot path, for example:

```text
supplier_catalog/providers/<provider_id>/snapshots/YYYY-MM-DD/
```

Each snapshot should include:

- `raw.html` or page-specific raw captures when useful.
- `extracted.json` with normalized categories/items.
- `diff.json` comparing the previous known snapshot.
- `summary.md` with a short human-readable change report.
