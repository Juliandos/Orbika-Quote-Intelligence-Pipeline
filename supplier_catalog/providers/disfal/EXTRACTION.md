# Disfal Extraction Notes

Provider: `disfal`

Website: `https://www.disfal.com/`

Reviewed public service page: `https://www.disfal.com/services/amortiguadores/`

Status: open website, no login required.

## Important Limitation

Disfal should be treated as a partial-verification supplier, not as an exact
reference source.

The visible public pages expose:

- product families
- supported commercial lines
- visible brands
- some series identifiers

The visible public pages do not reliably expose:

- exact OEM/reference codes
- stock
- public prices
- structured vehicle compatibility
- product-level detail cards for every line

For this reason, Disfal matches must stay inside:

```text
category_only
manual_confirmation_required
```

Recommended business action:

```text
Use Disfal as a trusted brand-family verification source, then confirm the exact
reference manually with the supplier.
```

## Relevant Public Areas

Two public areas are relevant:

1. The public home page, which exposes product-family links and visible brand
   landing pages.
2. Public service pages such as `amortiguadores`, which expose visible
   commercial lines and series labels.

## Extraction Target

From the home page, extract:

- `provider_id`
- `family_name`
- `family_url`
- `family_slug`
- `taxonomy_label`
- `source`
- `match_type`
- `requires_manual_confirmation`

From visible brand landing links, extract:

- `brand_name`
- `brand_url`
- `source`
- `notes`

From reviewed service pages, extract:

- `service_name`
- `service_url`
- `brand_name`
- `commercial_line`
- `series_label`
- `heading_text`
- `image_url`, when visible
- `taxonomy_label`
- `match_type`
- `match_confidence`
- `requires_manual_confirmation`
- `verification_note`

## Partial Verification Rule

Disfal data is useful for partial verification only.

That means:

- it can confirm that a supplier publicly handles a family such as
  `amortiguadores`, `suspension`, or `liquido_de_frenos`
- it can confirm that a known brand or commercial line appears on the supplier
  site
- it cannot confirm that a specific quote reference is available

Never promote a Disfal record to `exact_reference` unless a future reviewed page
exposes direct part references publicly.

## Classification Rule

Disfal data should feed the shared autoparts taxonomy.

Examples:

- `amortiguadores` -> `suspension_steering`
- `suspension` -> `suspension_steering`
- `correas` -> `belts_tensioners`
- `mangueras` -> `hoses_fluids`
- `tensores-poleas` -> `belts_tensioners`
- `sistemas-de-escape` -> `exhaust`
- `bujias` -> `ignition_electrical`
- `bomba-de-combustible` -> `fuel_delivery`
- `liquido-de-frenos` -> `brake_fluids`
- `crucetas` -> `driveline`

Keep both:

- the original visible family text
- the normalized taxonomy label

## Daily Snapshot Rule

Disfal must be refreshed every day at `07:00` local time.

Each daily refresh should create:

```text
supplier_catalog/providers/disfal/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/disfal/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/disfal/snapshots/YYYY-MM-DD/summary.md
```

The snapshot should report:

- new family links
- removed family links
- new or removed brand landing links
- new or removed reviewed commercial lines
- selector or page-read failures

## Adapter Notes

The adapter should remain read-only.

It must not:

- submit forms
- start chats
- access payment flows
- create orders
- login

The first implementation should prefer static HTTP/HTML extraction because the
reviewed public pages already expose the partial-verification information we
need.
