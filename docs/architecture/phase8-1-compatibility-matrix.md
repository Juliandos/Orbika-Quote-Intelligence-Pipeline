# Phase 8.1 Compatibility Matrix

This document freezes the initial compatibility vocabulary and regression set for Phase 8.1 before changing ranking or UI behavior.

## Goal

Make compatibility behavior reviewable and testable before tuning the matcher further. The current matcher already applies several deterministic checks. This matrix records which signals are treated as hard conflicts, soft warnings, or informational evidence in the current Phase 8.1 baseline.

## Current Evidence Vocabulary

| Signal | Meaning | Severity | Current behavior |
| --- | --- | --- | --- |
| `exact_reference` | Visible exact part/reference hit | hard-positive | Can produce score `100` and `exact_reference`. |
| `foreign_brand_detected` | Candidate clearly names a different vehicle brand | hard-negative | Rejected with score `0`. |
| `side_mismatch` | Left/right conflict | hard-negative | Rejected with score `0`. |
| `position_mismatch` | Front/rear or inner/outer conflict | hard-negative | Rejected with score `0`. |
| `year_mismatch` | Visible year or year range does not match quote year | soft-negative | Match may remain visible but score is capped at `45`. |
| `presentation_mismatch` | Requested kit/set conflicts with single-unit presentation | hard-negative | Rejected with score `0`. |
| `color_mismatch` | Visible color conflicts with requested color | soft-negative | Match remains visible but score is capped at `60`. |
| `finish_mismatch` | Visible finish conflicts with requested finish | soft-negative | Match remains visible but score is capped at `58`. |
| `vehicle_scoped_missing_line` | Vehicle-oriented title includes brand but not requested line | soft-negative | Score capped at `18`. |
| `vehicle_scoped_missing_version` | Brand and line appear but trim/version is missing | soft-negative | Score capped at `68`. |
| `preferred_provider` | Workshop preference favors a provider | informational-adjustment | Adds preference note and small score boost only if no hard conflict exists. |
| `avoided_provider` | Workshop preference penalizes a provider | informational-adjustment | Adds preference note and lowers score only if no hard conflict exists. |
| `prefer_exact_reference` | Workshop prefers exact reference when available | informational-adjustment | Non-exact candidates capped at `72`. |
| `category_only_provider_cap` | Provider exposes only category/family evidence | soft-negative | `Impocali` and `Disfal` stay capped and manual. |
| `unknown` | Missing visible evidence | unknown | Must stay unknown; no invented conflict should appear. |

## Curated Regression Set

The executable cases live in:

- `tests/fixtures/phase8_1_regression_cases.json`
- `tests/test_phase8_1_regression.py`

Initial curated cases:

1. Exact reference accepted.
2. Wrong side rejected.
3. Wrong position rejected.
4. Wrong year warned and capped.
5. Preferred provider lightly boosted.
6. Avoided provider penalized.
7. Exact-reference preference caps non-exact option.
8. Different brand rejected.
9. Vehicle-scoped candidate without requested line stays heavily capped.
10. Vehicle-scoped candidate without requested version stays partially capped.
11. Category-only provider remains manual.
12. Unknown/incomplete title stays unknown instead of inventing incompatibility.
13. Provider preference cannot override a hard side conflict.
14. Kit-versus-unit conflict is rejected.
15. Explicit color mismatch is capped and warned.
16. Explicit finish mismatch is capped and warned.

## Owner Review Instructions

The regression set is intentionally sanitized. The owner review should happen before changing scoring thresholds:

1. Review each case summary without looking at the encoded assertion first.
2. Mark whether the expected outcome is acceptable for the workshop.
3. Flag any wording that sounds too technical for daily use.
4. Approve or adjust which signals are hard, soft, or informational.
5. Only after this review, change ranking rules or UI evidence wording.

## Current Limitation

This baseline now includes deterministic handling for kit-versus-unit presentation, explicit color mismatch, and explicit finish mismatch. It still does not add new provider-specific parsers, generation parsing, body-style logic, or dimensional compatibility. Those remain later Phase 8.1 slices only if the owner confirms they are worth the added complexity.

