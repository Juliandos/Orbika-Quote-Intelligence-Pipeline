import json
import tempfile
import unittest
from pathlib import Path

from tools.agentic_match_reviewer import (
    enrich_quote_payload_with_agentic_review,
    review_quotes_dir,
)


class AgenticMatchReviewerTests(unittest.TestCase):
    def test_agentic_review_writes_separate_output(self) -> None:
        payload = {
            "quote_key": "quote-1",
            "orbika": {
                "marca": "KIA",
                "linea": "SPORTAGE [4]",
                "version": "VIBRANT TP 2000CC 2AB ABS CT",
                "parts": [],
            },
            "supplier_matching": {
                "generated_at": "2026-06-11T00:00:00+00:00",
                "parts": [
                    {
                        "part_name": "Protector motor",
                        "requested_reference": None,
                        "matches": [
                            {
                                "provider_id": "partcar",
                                "provider_name": "Partcar",
                                "score_percent": 76,
                                "match_type": "vehicle_compatible",
                                "product_name": "Protector Motor Inferior Para Kia Sportage",
                                "detail_url": "https://example.invalid/kia-sportage",
                                "brand": "KIA",
                                "category_name": "Carroceria",
                                "subcategory_name": None,
                                "reference": None,
                                "sku": None,
                                "reasons": [],
                            }
                        ],
                    }
                ],
            },
        }

        enriched = enrich_quote_payload_with_agentic_review(payload, limit_per_part=3)

        self.assertIn("supplier_matching", enriched)
        self.assertIn("agentic_supplier_matching", enriched)
        self.assertEqual(
            enriched["supplier_matching"]["parts"][0]["matches"][0]["product_name"],
            "Protector Motor Inferior Para Kia Sportage",
        )
        self.assertEqual(
            enriched["agentic_supplier_matching"]["summary"]["parts_with_agentic_matches"],
            1,
        )

    def test_agentic_review_collapses_same_provider_alternatives(self) -> None:
        payload = {
            "quote_key": "quote-2",
            "orbika": {
                "marca": "KIA",
                "linea": "SPORTAGE [4]",
                "version": "VIBRANT TP 2000CC 2AB ABS CT",
                "parts": [],
            },
            "supplier_matching": {
                "generated_at": "2026-06-11T00:00:00+00:00",
                "parts": [
                    {
                        "part_name": "Plumilla limpiavidrio panoramico trasero",
                        "requested_reference": None,
                        "matches": [
                            {
                                "provider_id": "parrales",
                                "provider_name": "Parrales",
                                "score_percent": 69,
                                "match_type": "vehicle_compatible",
                                "product_name": "PLUMILLA 16 PULG METALICA JGOX2",
                                "detail_url": "https://example.invalid/plumilla-16",
                                "brand": None,
                                "category_name": "Plumillas Limpiaparabrisas",
                                "subcategory_name": None,
                                "reference": None,
                                "sku": None,
                                "reasons": [],
                            },
                            {
                                "provider_id": "parrales",
                                "provider_name": "Parrales",
                                "score_percent": 68,
                                "match_type": "vehicle_compatible",
                                "product_name": "PLUMILLA 20 PULG AERODINAMICA CO- N 8 ADAPTADORES 1PCS",
                                "detail_url": "https://example.invalid/plumilla-20",
                                "brand": None,
                                "category_name": "Plumillas Limpiaparabrisas",
                                "subcategory_name": None,
                                "reference": None,
                                "sku": None,
                                "reasons": [],
                            },
                            {
                                "provider_id": "parrales",
                                "provider_name": "Parrales",
                                "score_percent": 67,
                                "match_type": "vehicle_compatible",
                                "product_name": "PLUMILLA AEROD. 22 PULG JGOX2",
                                "detail_url": "https://example.invalid/plumilla-22",
                                "brand": None,
                                "category_name": "Plumillas Limpiaparabrisas",
                                "subcategory_name": None,
                                "reference": None,
                                "sku": None,
                                "reasons": [],
                            },
                        ],
                    }
                ],
            },
        }

        enriched = enrich_quote_payload_with_agentic_review(payload, limit_per_part=3)
        matches = enriched["agentic_supplier_matching"]["parts"][0]["selected_matches"]

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["provider_id"], "parrales")
        self.assertIn("plumilla", matches[0]["product_name"].lower())
        self.assertEqual(matches[0]["rank"], 1)
        self.assertTrue(matches[0]["agentic_comment"])

    def test_agentic_review_rejects_wrong_part_type(self) -> None:
        payload = {
            "quote_key": "quote-3",
            "orbika": {
                "marca": "KIA",
                "linea": "SPORTAGE [4]",
                "version": "VIBRANT TP 2000CC 2AB ABS CT",
                "parts": [],
            },
            "supplier_matching": {
                "generated_at": "2026-06-11T00:00:00+00:00",
                "parts": [
                    {
                        "part_name": "Filtro de combustible",
                        "requested_reference": None,
                        "matches": [
                            {
                                "provider_id": "repuestera",
                                "provider_name": "Repuestera",
                                "score_percent": 72,
                                "match_type": "vehicle_compatible",
                                "product_name": "FILTRO COMBUSTIBLE KIA SPORTAGE",
                                "detail_url": "https://example.invalid/filtro",
                                "brand": "KIA",
                                "category_name": "Filtros",
                                "subcategory_name": None,
                                "reference": None,
                                "sku": None,
                                "reasons": [],
                            },
                            {
                                "provider_id": "disfal",
                                "provider_name": "Disfal",
                                "score_percent": 61,
                                "match_type": "vehicle_compatible",
                                "product_name": "Bomba de combustible",
                                "detail_url": "https://example.invalid/bomba",
                                "brand": None,
                                "category_name": "Combustible",
                                "subcategory_name": None,
                                "reference": None,
                                "sku": None,
                                "reasons": [],
                            },
                        ],
                    }
                ],
            },
        }

        enriched = enrich_quote_payload_with_agentic_review(payload, limit_per_part=5)
        matches = enriched["agentic_supplier_matching"]["parts"][0]["selected_matches"]

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["detail_url"], "https://example.invalid/filtro")

    def test_agentic_review_collapses_repeated_provider_options(self) -> None:
        payload = {
            "quote_key": "quote-4",
            "orbika": {
                "marca": "KIA",
                "linea": "SPORTAGE [4]",
                "version": "VIBRANT TP 2000CC 2AB ABS CT",
                "parts": [],
            },
            "supplier_matching": {
                "generated_at": "2026-06-11T00:00:00+00:00",
                "parts": [
                    {
                        "part_name": "Bujias",
                        "requested_reference": None,
                        "matches": [
                            {
                                "provider_id": "parrales",
                                "provider_name": "Parrales",
                                "score_percent": 83,
                                "match_type": "category_only",
                                "detail_url": "https://example.invalid/bujia-1",
                                "product_name": "BUJIA ENCENDIDO (BM6A)",
                                "reference": "BM6A",
                                "sku": "SKU-1",
                                "brand": None,
                                "category_name": "Repuestos Electricos",
                                "subcategory_name": "Bujias",
                                "reasons": [],
                            },
                            {
                                "provider_id": "parrales",
                                "provider_name": "Parrales",
                                "score_percent": 82,
                                "match_type": "category_only",
                                "detail_url": "https://example.invalid/bujia-2",
                                "product_name": "BUJIA ENCENDIDO (BKR5ES)",
                                "reference": "BKR5ES",
                                "sku": "SKU-2",
                                "brand": None,
                                "category_name": "Repuestos Electricos",
                                "subcategory_name": "Bujias",
                                "reasons": [],
                            },
                            {
                                "provider_id": "disfal",
                                "provider_name": "Disfal",
                                "score_percent": 55,
                                "match_type": "manual_confirmation_required",
                                "detail_url": "https://example.invalid/disfal-bujias",
                                "product_name": "Bujias",
                                "reference": None,
                                "sku": None,
                                "brand": None,
                                "category_name": "Bujias",
                                "subcategory_name": None,
                                "reasons": [],
                            },
                        ],
                    }
                ],
            },
        }

        enriched = enrich_quote_payload_with_agentic_review(payload, limit_per_part=8)
        matches = enriched["agentic_supplier_matching"]["parts"][0]["selected_matches"]

        self.assertEqual(len(matches), 2)
        self.assertEqual(
            [match["provider_id"] for match in matches],
            ["parrales", "disfal"],
        )

    def test_review_quotes_dir_writes_trace_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            quotes_dir = root / "quotes"
            trace_dir = root / "traces"
            quotes_dir.mkdir()
            (quotes_dir / "quote.json").write_text(
                json.dumps(
                    {
                        "quote_key": "trace-quote",
                        "orbika": {
                            "marca": "KIA",
                            "linea": "SPORTAGE",
                            "version": "VIBRANT",
                            "parts": [],
                        },
                        "supplier_matching": {
                            "generated_at": "2026-06-11T00:00:00+00:00",
                            "parts": [
                                {
                                    "part_name": "Bujias",
                                    "requested_reference": None,
                                    "matches": [
                                        {
                                            "provider_id": "parrales",
                                            "provider_name": "Parrales",
                                            "score_percent": 74,
                                            "match_type": "vehicle_compatible",
                                            "product_name": "BUJIA ENCENDIDO (BKR5ES)",
                                            "detail_url": "https://example.invalid/bujia-1",
                                            "brand": None,
                                            "category_name": "Bujias",
                                            "subcategory_name": None,
                                            "reference": None,
                                            "sku": None,
                                            "reasons": [],
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = review_quotes_dir(quotes_dir=quotes_dir, trace_dir=trace_dir, limit_per_part=3)

            self.assertEqual(result["quotes_reviewed"], 1)
            self.assertEqual(len(result["trace_paths"]), 1)
            self.assertTrue((trace_dir / "trace-quote.agentic_trace.json").exists())
