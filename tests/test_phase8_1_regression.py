import json
import unittest
from pathlib import Path

from tools.supplier_quote_matcher import (
    ProviderItem,
    infer_taxonomies,
    normalize_reference,
    part_query_tokens,
    score_item,
    vehicle_profile_from_quote_context,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phase8_1_regression_cases.json"


def _provider_item(payload: dict) -> ProviderItem:
    return ProviderItem(
        provider_id=payload["provider_id"],
        provider_name=payload["provider_name"],
        provider_type=payload["provider_type"],
        detail_url=None,
        title=payload["title"],
        category_name=payload.get("category_name"),
        subcategory_name=payload.get("subcategory_name"),
        brand=payload.get("brand"),
        reference=payload.get("reference"),
        sku=payload.get("sku"),
        supplier_item_code=payload.get("supplier_item_code"),
        taxonomy_labels=tuple(payload.get("taxonomy_labels") or ()),
        searchable_tokens=frozenset(payload.get("searchable_tokens") or ()),
        raw_match_type=payload.get("raw_match_type"),
        requires_manual_confirmation=bool(payload.get("requires_manual_confirmation", True)),
        notes=tuple(payload.get("notes") or ()),
    )


class Phase81RegressionTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8-sig"))

    def test_regression_cases_match_current_compatibility_contract(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                part = case["part"]
                quote_context = case["quote_context"]
                item = _provider_item(case["item"])
                preferences = case.get("preferences") or {}
                score, reasons, match_type, risk_flags, preference_notes = score_item(
                    part_name=part["name"],
                    requested_reference=normalize_reference(part.get("reference")),
                    part_tokens=part_query_tokens(part["name"], part.get("reference")),
                    quote_context=quote_context,
                    quote_vehicle=vehicle_profile_from_quote_context(quote_context),
                    requested_taxonomies=infer_taxonomies(part["name"], part.get("reference")),
                    item=item,
                    preferences=preferences,
                )
                expected = case["expected"]

                if "score_equals" in expected:
                    self.assertEqual(score, expected["score_equals"])
                if "minimum_score" in expected:
                    self.assertGreaterEqual(score, expected["minimum_score"])
                if "maximum_score" in expected:
                    self.assertLessEqual(score, expected["maximum_score"])
                if "match_type" in expected:
                    self.assertEqual(match_type, expected["match_type"])
                if expected.get("risk_flags_empty"):
                    self.assertEqual(risk_flags, [])
                if expected.get("preference_notes_empty"):
                    self.assertEqual(preference_notes, [])

                joined_reasons = " ".join(reasons).lower()
                joined_notes = " ".join(preference_notes).lower()
                for fragment in expected.get("risk_flags_contains", []):
                    self.assertIn(fragment, risk_flags)
                for fragment in expected.get("reason_contains", []):
                    self.assertIn(fragment.lower(), joined_reasons)
                for fragment in expected.get("preference_notes_contains", []):
                    self.assertIn(fragment.lower(), joined_notes)


if __name__ == "__main__":
    unittest.main()

