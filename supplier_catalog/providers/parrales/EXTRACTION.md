# Parrales Extraction Notes

Provider: `parrales`

Website: `https://parrales.com.co/tienda/`

Status: open website, no login required.

## Why This Provider Is Stronger

Unlike Impocali, Parrales exposes product-level catalog records directly on the
 public store pages.

Visible product data may include:

- product name
- price
- sale price and original price
- category and subcategory from the filter tree
- brand
- reference
- SKU
- technical attributes in the detail page
- free-text description

This makes Parrales a candidate for:

- `exact_reference`
- `vehicle_compatible`
- `category_only`

depending on what the product page actually exposes.

## Relevant Catalog Root

- Store root: `https://parrales.com.co/tienda/`

The filter panel acts as the public catalog index.

## Public Filter Taxonomy Observed

Top-level categories currently visible:

- Cables electricos
- Iluminacion
- Lujos y accesorios
- Miscelanea electrica
- Pitos
- Plumillas limpiaparabrisas
- Repuestos electricos
- Repuestos mecanicos

Observed subcategories include:

- AWG
- Bateria
- Cables de desvare
- Duplex
- Encauchetado
- Barras Led
- Bombillos Led
- Exploradoras
- Luz halogena
- Forros
- Tapetes
- Elevavidrios
- Medidores
- Peras
- Sensores
- Switches
- Terminales
- Cornetas
- De disco
- De reversa
- Oreja de perro
- Sirenas
- Aerodinamicas
- Hibridas
- Metalicas
- Trasera
- Alternadores
- Arranques
- Bobinas
- Bujias
- Reguladores
- Amortiguadores
- Rodamientos

## Extraction Target

For each product, extract:

- `provider_id`
- `product_name`
- `product_url`
- `image_url`
- `price_current`
- `price_original`, when present
- `on_sale`
- `currency`
- `brand`, when present
- `reference`, when present
- `sku`, when present
- `category`
- `subcategory`
- `description`, when present
- `technical_attributes`
- `searchable_tokens`
- `source_url`
- `match_type`
- `match_confidence`
- `requires_manual_confirmation`

## Matching Rule

Use this priority:

1. Exact reference match from `reference`, `sku`, or reference-like text inside
   the product name.
2. Vehicle or compatibility match from the detail page description.
3. Brand + normalized product type match.
4. Category-only fallback.

## Product Detail Fields Seen Publicly

At least some product detail pages expose:

- `MARCA`
- `REF`
- `SKU`
- voltage, watts, or other technical specs
- compatibility notes
- description text

Example observed publicly on a detail page:

- `MARCA: VEKTRA`
- `REF: VKH-9101`
- `SKU: JN-9101`

## Daily Snapshot Rule

Parrales must be refreshed every day at `07:00` local time.

Each daily refresh should create:

```text
supplier_catalog/providers/parrales/snapshots/YYYY-MM-DD/extracted.json
supplier_catalog/providers/parrales/snapshots/YYYY-MM-DD/diff.json
supplier_catalog/providers/parrales/snapshots/YYYY-MM-DD/summary.md
```

## Adapter Notes

The adapter should:

1. Read the filter tree.
2. Walk the paginated catalog.
3. Capture every product card.
4. Visit each product detail page.
5. Normalize exact and approximate matching signals.

The adapter must remain read-only. No cart, no checkout, no login.
