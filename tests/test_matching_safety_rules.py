import unittest

from tools.agentic_match_reviewer import build_agentic_match_report
from tools.supplier_quote_matcher import (
    ProviderItem,
    infer_part_family,
    part_family_is_compatible,
    part_query_tokens,
    score_item,
    vehicle_profile_from_quote_context,
    infer_taxonomies,
)


class MatchingSafetyRuleTests(unittest.TestCase):
    def test_specific_families_do_not_cross(self) -> None:
        self.assertEqual(infer_part_family("Aceite 1/4"), "engine_oil")
        self.assertEqual(infer_part_family("Filtro de aceite"), "oil_filter")
        self.assertEqual(infer_part_family("Porta bocin delantero derecho"), "horn_mount")
        self.assertFalse(part_family_is_compatible("oil_filter", "cabin_filter"))
        self.assertFalse(part_family_is_compatible("bumper_support", "bumper_cover"))
        self.assertFalse(part_family_is_compatible("horn_mount", "horn"))

    def test_oil_filter_does_not_accept_cabin_filter(self) -> None:
        item = ProviderItem(
            provider_id="test",
            provider_name="Test",
            provider_type="product",
            detail_url="https://example.invalid/product",
            title="Filtro de aire acondicionado Kia Sportage",
            category_name="Filtros",
            subcategory_name="Filtros aire acondicionado",
            brand="KIA",
            reference=None,
            sku=None,
            supplier_item_code=None,
            taxonomy_labels=("filters",),
            searchable_tokens=frozenset(
                {"filtro", "aire", "acondicionado", "kia", "sportage"}
            ),
            raw_match_type="category_only",
            requires_manual_confirmation=True,
            notes=(),
        )
        score, reasons, match_type, *_ = score_item(
            part_name="Filtro de aceite",
            requested_reference=None,
            part_tokens=part_query_tokens("Filtro de aceite", None),
            quote_context={"marca": "KIA", "linea": "SPORTAGE", "version": "2016"},
            quote_vehicle=vehicle_profile_from_quote_context(
                {"marca": "KIA", "linea": "SPORTAGE", "version": "2016"}
            ),
            requested_taxonomies=infer_taxonomies("Filtro de aceite", None),
            item=item,
            preferences={},
        )
        self.assertEqual(score, 0)
        self.assertEqual(match_type, "manual_confirmation_required")
        self.assertTrue(any("family" in reason.lower() for reason in reasons))

    def test_empty_quote_never_gets_agentic_matches(self) -> None:
        report = build_agentic_match_report(
            {
                "orbika": {"parts": [], "repuestos_count": 0},
                "supplier_matching": {
                    "parts": [
                        {
                            "part_name": "Producto que no debe existir",
                            "matches": [{"provider_id": "bad"}],
                        }
                    ]
                },
            }
        )
        self.assertEqual(report["review_mode"], "skipped_empty_quote")
        self.assertEqual(report["parts"], [])
        self.assertEqual(report["summary"]["parts_with_agentic_matches"], 0)


if __name__ == "__main__":
    unittest.main()
