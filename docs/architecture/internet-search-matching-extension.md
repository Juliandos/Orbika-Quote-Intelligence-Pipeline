# Extension Proposal: Web Search Matches Per Requested Part

## Objective

Add a second discovery layer to Orbika Quote Intelligence Pipeline that performs a live internet search per requested part and returns up to 5 validated external links.

This new layer must:

- complement the current local supplier catalog matching
- never replace the current deterministic matcher by default
- remain clearly separated in backend responses and in the frontend
- only surface candidates that belong to the same part family as the requested part
- prioritize functional validity over coverage

The desired user-facing behavior is:

- each requested part keeps its current local catalog matches
- optionally, the system also shows a new section called something like `Busqueda en internet`
- that section returns at most 5 validated links
- those links must be substantially safer than raw search engine results

## Current Project Context

Today the project has two core matching stages:

1. `tools/supplier_quote_matcher.py`
   This is the deterministic layer based on extracted local supplier catalogs and normalized scoring logic.

2. `tools/agentic_match_reviewer.py`
   This is the review layer that receives deterministic candidates, removes invalid ones, reorders them, and explains decisions.

The project also depends heavily on provider extractors because the local matching universe is only as good as the extracted supplier snapshots.

This means the current system has a real structural limitation:

- if a product exists on the internet but is not present in the extracted local supplier catalogs, the deterministic matcher cannot recommend it

That is why a controlled web search layer is valuable.

## High-Level Architecture

Add a new module:

- `tools/internet_quote_matcher.py`

Its job is:

1. Receive one requested part plus vehicle context.
2. Build a targeted search query.
3. Fetch candidate result URLs from the internet search layer.
4. Open each candidate page and extract structured evidence.
5. Reject invalid candidates using strict family and compatibility rules.
6. Return at most 5 validated candidates with explicit provenance.

This should be modeled as a parallel but separate source, not as a mutation of the existing local catalog source.

Recommended response structure per requested part:

```json
{
  "part_name": "Bomper trasero",
  "reference": "7181165DC1799",
  "local_matches": [],
  "internet_matches": [
    {
      "source_type": "internet_search",
      "provider_name": "Importadoras Asociadas",
      "product_name": "Bomper trasero Suzuki Grand Vitara",
      "product_url": "https://example.com/producto",
      "score": 91,
      "confidence": "validated",
      "reason": "Misma familia de repuesto y evidencia fuerte en titulo y referencia",
      "evidence": {
        "query": "bomper trasero chevrolet grand vitara 2007 7181165DC1799",
        "title": "Bomper trasero Suzuki Grand Vitara",
        "reference_text": "7181165DC1799",
        "vehicle_mentions": ["grand vitara", "2007"],
        "brand_mentions": ["suzuki", "chevrolet"]
      }
    }
  ]
}
```

## Source Separation

The frontend should never merge `local_matches` and `internet_matches` into a single undifferentiated list.

Recommended UX:

- `Coincidencias del catalogo`
- `Busqueda en internet`

Each internet result should show:

- source badge like `Internet`
- provider or domain
- score
- explanation
- warning if it is only probable and not strongly validated

This keeps trust high and makes debugging easier.

## Query Construction

The search query must be built from the actual quote part, not from supplier product names.

Priority fields:

- requested part name
- validated reference if present
- vehicle brand
- vehicle line or model
- vehicle year

Recommended query template:

```text
{part_name} {vehicle_brand} {vehicle_line} {vehicle_year} {reference}
```

Examples:

- `bomper trasero chevrolet grand vitara 2007 7181165DC1799`
- `filtro de aceite kia sportage 2016 2631027200`
- `bisagra derecha capo kia sportage 2016`

Rules:

- if reference exists, include it
- if line or version is noisy, normalize before query creation
- remove generic noise like `genuino`, `cotizar`, `repuesto`, `colombia` unless needed

## Candidate Validation Rules

This is the most important part of the design.

The raw search result is never enough to display a candidate.

Each candidate page must be validated with extracted evidence.

### Hard Rule 1: Same Part Family

If the requested part is from one family, the candidate cannot belong to a clearly different family.

Examples:

- `bomper trasero` cannot become `guia soporte bomper`
- `bomper trasero` cannot become `bujia`
- `bomper trasero` cannot become `manguera`
- `emblema compuerta` cannot become `kit distribucion`
- `empaque vidrio parabrisas` cannot become `empaque culata`
- `filtro de aceite` cannot become `filtro de aire`
- `aceite 1/4` cannot become `filtro de aceite`
- `guardafango derecho` cannot become `pin guardafango`
- `compuerta trasera completa` cannot become `amortiguador compuerta`
- `exploradora derecha` cannot become `bocel exploradora`

The rule is not word-overlap based.
It is family based.

### Hard Rule 2: Evidence Must Come From the Product Page

Validation must use page-level evidence such as:

- product title
- visible part number
- visible compatible vehicles
- visible brand/model text
- breadcrumb or category if strongly indicative

A search result snippet alone is not enough.

### Hard Rule 3: Maximum Five Validated Links

The layer should evaluate more than five candidates if necessary, but only return the top five validated links.

### Soft Rule 1: Brand Compatibility Matters

If the page explicitly shows vehicle brand/model compatibility and it does not fit, the score must drop heavily.

But do not hard reject every cross-brand result because some parts are generic or cross-compatible:

- bearings
- seals
- gaskets
- fluids
- tires
- fasteners

So:

- structural body parts should be strict on compatibility
- consumables and generic components can be more flexible

### Soft Rule 2: Reference Helps But Is Not Mandatory

If reference exists and matches, boost strongly.
If no reference exists, a candidate may still be valid if the family and compatibility evidence are strong.

### Soft Rule 3: Ambiguous Cases Go To Lower Confidence

If family is correct but compatibility evidence is incomplete, keep it only as:

- `confidence = probable`

Do not present it as a strong validated result.

## Suggested Backend Contract

Extend the current matching report shape with an optional internet block.

Recommended per part:

```json
{
  "part_name": "Filtro de aceite",
  "reference": "2631027200",
  "matches": [...],
  "internet_search": {
    "enabled": true,
    "query": "filtro de aceite kia sportage 2016 2631027200",
    "results_found": 14,
    "validated_results": 3,
    "items": [...]
  }
}
```

Recommended top-level metadata:

```json
{
  "internet_search_summary": {
    "enabled": true,
    "parts_processed": 8,
    "parts_with_results": 5,
    "total_validated_links": 12
  }
}
```

## Suggested Processing Strategy

Do not run internet search for every part blindly at first.

Phase the rollout:

### Phase 1

Only trigger internet search when:

- there are no valid local matches
- or the best local match score is below a threshold like 70

### Phase 2

Allow internet search for all parts, but keep it optional behind a flag.

### Phase 3

Blend local plus web evidence into the agentic reviewer, still keeping source separation in the UI.

## Integration with `supplier_quote_matcher.py`

Do not overload the deterministic local matcher with live internet logic.

Instead:

- keep `supplier_quote_matcher.py` focused on local supplier catalogs
- call `internet_quote_matcher.py` as a separate step after deterministic matching

Recommended orchestration:

1. parse quote
2. run local deterministic matcher
3. run agentic reviewer on local candidates
4. if local result is empty or weak, run internet matcher
5. validate and attach internet results
6. optionally run a second review pass on internet results

## Integration with `agentic_match_reviewer.py`

The agentic reviewer should understand candidate provenance.

Every candidate should include:

- `source_type = local_catalog | internet_search`

Reviewer responsibilities for internet candidates:

- reject wrong-family results
- reject obvious compatibility conflicts
- rank validated candidates from best to worst
- generate human-readable justification for the workshop owner

This is especially important because the internet layer can bring higher recall but also higher noise.

## Provider and Domain Policy

Not every domain should be accepted equally.

Recommended domain tiers:

- Tier 1: current known suppliers already linked to Orbika
- Tier 2: high-confidence automotive marketplaces already seen in user validation
- Tier 3: unknown domains, only if page evidence is strong

Early rollout should prefer Tier 1 and Tier 2.

This reduces junk dramatically.

## Frontend Proposal

Per requested part, add a second result group:

- `Busqueda en internet`

Each row should display:

- product title
- provider or domain
- score
- confidence label: `Validado`, `Probable`, `Revision manual`
- short reason
- clickable link

Recommended visual behavior:

- hide the section if there are zero validated results
- do not mix it inside the same ranking as local matches
- show a small explanatory note:
  `Resultados externos validados por reglas de coincidencia. No reemplazan las coincidencias del catalogo local.`

## Operational Risks

### Risk 1: Latency

Live internet search will be slower than local matching.

Mitigation:

- limit to parts with weak or empty local matches
- cache search results by normalized query
- store extracted page evidence for reuse

### Risk 2: Search Noise

Search engines return misleading results.

Mitigation:

- validate product pages, not snippets
- same-family filtering
- maximum 5 validated links

### Risk 3: Site Blocking

Some sites may rate-limit or block automated traffic.

Mitigation:

- prefer lightweight fetch and HTML parse first
- use browser automation only when necessary
- add provider/domain throttling

### Risk 4: False Confidence

Even good-looking web results can still be wrong.

Mitigation:

- explicit provenance
- confidence labels
- stronger review logic for body parts and structural components

## Suggested Implementation Steps

### Step 1

Create `tools/internet_quote_matcher.py` with:

- query builder
- result normalizer
- page validator
- top-5 output contract

### Step 2

Add a feature flag like:

- `ENABLE_INTERNET_SEARCH_MATCHES=true`

### Step 3

Integrate this in the backend response shape without touching existing local match behavior.

### Step 4

Update the frontend types and UI with a separate section.

### Step 5

Add regression tests for:

- empty quote returns no internet results
- wrong-family results are rejected
- `filtro de aceite` does not accept `filtro de aire`
- `aceite 1/4` does not accept `filtro de aceite`
- `bomper trasero` does not accept `guia soporte bomper`
- max 5 results

## Validation Checklist

The feature is acceptable only if all of these are true:

- local catalog matches still work exactly as before
- internet results are clearly separated from local results
- no part shows more than 5 internet links
- wrong-family results are not shown
- empty quotes show zero internet matches
- body-part requests are stricter than generic consumables
- each internet result has an explanation and provenance

## Recommendation

This feature is worth building, but only as a validated second layer.

If implemented as raw search output, it will likely increase noise.
If implemented with strict family validation and clear UI separation, it can materially improve coverage for missing products without damaging trust in the system.
