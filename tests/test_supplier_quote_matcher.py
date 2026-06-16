import json
import tempfile
import unittest
from pathlib import Path

from tools.supplier_quote_matcher import (
    build_quote_match_report,
    enrich_quote_payload,
    load_provider_catalog_index,
    rebuild_daily_reports,
    write_quote_payload,
)


class SupplierQuoteMatcherTests(unittest.TestCase):
    def test_write_quote_payload_compacts_matching_sections(self) -> None:
        payload = {
            "quote_key": "quote-1",
            "source": {
                "gmail_id": "gmail-1",
                "message_id": "<message-1>",
                "internal_date_ms": "123",
                "received_at": "2026-06-11T00:00:00+00:00",
                "subject": "Quote",
                "sender": "Orbika <cotizacionesorbika@subocol.com>",
            },
            "quote_url": "https://example.invalid/quote?token=secret",
            "quote_url_masked": "https://example.invalid/quote?<redacted>",
            "orbika": {
                "quote_url": "https://example.invalid/quote?token=secret",
                "marca": "KIA",
                "parts": [
                    {
                        "name": "Capo",
                        "reference": "664003W001",
                        "quantity": 1,
                        "reference_input_value": "664003W001",
                        "visible_dom_values": {"reference": "664003W001"},
                    }
                ],
            },
            "supplier_matching": {
                "generated_at": "2026-06-11T00:00:00+00:00",
                "provider_snapshot_dates": {"repuestera": "2026-06-09"},
                "summary": {"parts_total": 1, "parts_with_matches": 1},
                "provider_specs": [
                    {
                        "provider_id": "repuestera",
                        "display_name": "Repuestera",
                        "website": "https://example.invalid/repuestera",
                        "snapshot_date": "2026-06-09",
                        "notes": ["Too verbose"],
                    }
                ],
                "parts": [
                    {
                        "part_name": "Capo",
                        "requested_reference": "664003W001",
                        "requested_taxonomies": ["body_panels"],
                        "matches": [
                            {
                                "provider_id": "repuestera",
                                "provider_name": "Repuestera",
                                "score_percent": 100,
                                "match_type": "exact_reference",
                                "detail_url": "https://example.invalid/capo",
                                "product_name": "CAPO SPORTAGE",
                                "reference": "664003W001",
                                "reasons": ["Exact reference"],
                                "notes": ["Verbose"],
                            },
                            {
                                "provider_id": "partcar",
                                "provider_name": "Partcar",
                                "score_percent": 77,
                                "match_type": "category_only",
                                "detail_url": "https://example.invalid/capo-2",
                                "product_name": "CAPO 2",
                            },
                            {
                                "provider_id": "parrales",
                                "provider_name": "Parrales",
                                "score_percent": 75,
                                "match_type": "category_only",
                                "detail_url": "https://example.invalid/capo-3",
                                "product_name": "CAPO 3",
                            },
                            {
                                "provider_id": "impocali",
                                "provider_name": "Impocali",
                                "score_percent": 55,
                                "match_type": "manual_confirmation_required",
                                "detail_url": "https://example.invalid/capo-4",
                                "product_name": "CAPO 4",
                            }
                        ],
                    }
                ],
            },
            "agentic_supplier_matching": {
                "generated_at": "2026-06-11T00:00:00+00:00",
                "review_mode": "heuristic_fallback",
                "summary": {"parts_reviewed": 1, "parts_with_agentic_matches": 1},
                "parts": [
                    {
                        "part_name": "Capo",
                        "selected_count": 1,
                        "selected_matches": [
                            {
                                "rank": 1,
                                "provider_id": "repuestera",
                                "provider_name": "Repuestera",
                                "score_percent": 100,
                                "match_type": "exact_reference",
                                "product_name": "CAPO SPORTAGE",
                                "detail_url": "https://example.invalid/capo",
                            }
                        ],
                        "trace": [{"stage": "review"}],
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "quote.json"
            write_quote_payload(path, payload)
            stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("quote_url", stored)
        self.assertNotIn("gmail_id", stored["source"])
        self.assertNotIn("internal_date_ms", stored["source"])
        self.assertNotIn("quote_url", stored["orbika"])
        self.assertNotIn("visible_dom_values", stored["orbika"]["parts"][0])
        self.assertNotIn("reference_input_value", stored["orbika"]["parts"][0])
        self.assertNotIn("provider_snapshot_dates", stored["supplier_matching"])
        self.assertNotIn("notes", stored["supplier_matching"]["provider_specs"][0])
        self.assertNotIn("website", stored["supplier_matching"]["provider_specs"][0])
        self.assertNotIn("reasons", stored["supplier_matching"]["parts"][0]["matches"][0])
        self.assertNotIn("supplier_item_code", stored["supplier_matching"]["parts"][0]["matches"][0])
        self.assertEqual(len(stored["supplier_matching"]["parts"][0]["matches"]), 3)
        self.assertNotIn("partial_matches", stored["supplier_matching"]["summary"])
        self.assertNotIn("manual_confirmation_only", stored["supplier_matching"]["summary"])
        self.assertNotIn("trace", stored["agentic_supplier_matching"]["parts"][0])
        self.assertNotIn("selected_count", stored["agentic_supplier_matching"]["parts"][0])
        self.assertNotIn("notes", stored["agentic_supplier_matching"]["parts"][0])
        self.assertNotIn("langgraph_available", stored["agentic_supplier_matching"])

    def test_build_quote_match_report_finds_exact_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "repuestera"
            (provider_dir / "snapshots" / "2026-06-09").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Repuestera",
                        "website": "https://example.invalid/repuestera",
                        "matching": {"notes": "Prefer exact references."},
                        "data_precision": {"reference_codes": True},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-09" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-09",
                        "products": [
                            {
                                "reference": "664003W001",
                                "product_name": "CAPO SPORTAGE",
                                "brand": "KIA",
                                "category_name": "CARROCERIA",
                                "detail_url": "https://example.invalid/capo",
                                "searchable_tokens": ["664003w001", "capo", "sportage", "kia"],
                                "match_type": "exact_reference",
                                "requires_manual_confirmation": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "source": {"subject": "Quote"},
                "orbika": {
                    "marca": "KIA",
                    "linea": "sportage",
                    "version": "revolution",
                    "ano": "2016",
                    "parts": [
                        {
                            "name": "Capo",
                            "reference": "664003W001",
                            "quantity": 1,
                        }
                    ],
                },
            },
            index=index,
            limit_per_part=3,
        )

        self.assertEqual(report["summary"]["parts_with_matches"], 1)
        self.assertEqual(report["summary"]["exact_reference_matches"], 1)
        best = report["parts"][0]["matches"][0]
        self.assertEqual(best["provider_id"], "repuestera")
        self.assertEqual(best["match_type"], "exact_reference")
        self.assertEqual(best["score_percent"], 100)

    def test_build_quote_match_report_marks_impocali_as_manual_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "impocali"
            (provider_dir / "snapshots" / "2026-06-09").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Impocali",
                        "website": "https://example.invalid/impocali",
                        "matching": {"notes": "Category only."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-09" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-09",
                        "products": [
                            {
                                "segment": "autos",
                                "category_name": "Suspension y Direccion",
                                "category_url": "https://example.invalid/suspension",
                                "taxonomy": "suspension_steering",
                                "product_names": ["Amortiguadores"],
                            }
                        ],
                        "notes": ["Public categories only."],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "CHEVROLET",
                    "linea": "AVEO",
                    "parts": [
                        {
                            "name": "Amortiguador delantero derecho",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=3,
        )

        best = report["parts"][0]["matches"][0]
        self.assertEqual(best["provider_id"], "impocali")
        self.assertEqual(best["match_type"], "manual_confirmation_required")
        self.assertTrue(best["requires_manual_confirmation"])
        self.assertIn("referencia exacta publica", best["summary"])

    def test_build_quote_match_report_rejects_foreign_brand_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "partcar"
            (provider_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Partcar",
                        "website": "https://example.invalid/partcar",
                        "matching": {"notes": "Use provider code carefully."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "product_name": "Protector Motor Inferior Para Chevrolet Spark",
                                "detail_url": "https://example.invalid/chevrolet",
                                "taxonomy_label": "body_panels",
                                "searchable_tokens": [
                                    "protector",
                                    "motor",
                                    "inferior",
                                    "chevrolet",
                                    "spark",
                                ],
                            },
                            {
                                "product_name": "Protector Motor Inferior Para Kia Sportage",
                                "detail_url": "https://example.invalid/kia-sportage",
                                "taxonomy_label": "body_panels",
                                "searchable_tokens": [
                                    "protector",
                                    "motor",
                                    "inferior",
                                    "kia",
                                    "sportage",
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Protector motor",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["product_name"], "Protector Motor Inferior Para Kia Sportage")
        self.assertEqual(matches[0]["detail_url"], "https://example.invalid/kia-sportage")

    def test_build_quote_match_report_demotes_same_brand_wrong_line_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "parrales"
            (provider_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Parrales",
                        "website": "https://example.invalid/parrales",
                        "matching": {"notes": "Public catalog."},
                        "data_precision": {"reference_codes": True},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "product_name": "Cuna De Motor Para Kia Cerato Modelos 2013 A 2016",
                                "product_url": "https://example.invalid/kia-cerato",
                                "category_name": "Motor",
                                "brand": "KIA",
                                "reference": None,
                                "sku": None,
                                "searchable_tokens": [
                                    "cuna",
                                    "motor",
                                    "kia",
                                    "cerato",
                                    "modelos",
                                    "2013",
                                    "2016",
                                ],
                            },
                            {
                                "product_name": "Cuna De Motor Para Kia Sportage Modelos 2020 A 2024",
                                "product_url": "https://example.invalid/kia-sportage",
                                "category_name": "Motor",
                                "brand": "KIA",
                                "reference": None,
                                "sku": None,
                                "searchable_tokens": [
                                    "cuna",
                                    "motor",
                                    "kia",
                                    "sportage",
                                    "modelos",
                                    "2020",
                                    "2024",
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Cubierta superior motor",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["product_name"], "Cuna De Motor Para Kia Sportage Modelos 2020 A 2024")
        self.assertGreater(matches[0]["score_percent"], 0)
        self.assertLess(matches[0]["score_percent"], 70)

    def test_build_quote_match_report_ignores_direction_only_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "partcar"
            (provider_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Partcar",
                        "website": "https://example.invalid/partcar",
                        "matching": {"notes": "Partial public catalog."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "product_name": "Stop Izquierdo Para Kia Sportage Modelos 2017 A 2019 Tyc",
                                "detail_url": "https://example.invalid/stop",
                                "taxonomy_label": "lighting_headlamps",
                                "searchable_tokens": [
                                    "stop",
                                    "izquierdo",
                                    "kia",
                                    "sportage",
                                    "modelos",
                                    "2017",
                                    "2019",
                                ],
                            },
                            {
                                "product_name": "Exploradora Izquierda Para Kia Sportage Modelos 2017 A 2019 Tyc",
                                "detail_url": "https://example.invalid/exploradora",
                                "taxonomy_label": "lighting_headlamps",
                                "searchable_tokens": [
                                    "exploradora",
                                    "izquierda",
                                    "kia",
                                    "sportage",
                                    "modelos",
                                    "2017",
                                    "2019",
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Exploradora izquierdo",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertEqual(matches[0]["product_name"], "Exploradora Izquierda Para Kia Sportage Modelos 2017 A 2019 Tyc")

    def test_build_quote_match_report_rejects_same_vehicle_unrelated_product(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "partcar"
            (provider_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Partcar",
                        "website": "https://example.invalid/partcar",
                        "matching": {"notes": "Partial public catalog."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "product_name": "Defensa Bomper Delantero Para Kia Sportage Modelos 2019 A 2022 Fpi",
                                "detail_url": "https://example.invalid/defensa",
                                "taxonomy_label": "body_panels",
                                "searchable_tokens": [
                                    "defensa",
                                    "bomper",
                                    "delantero",
                                    "kia",
                                    "sportage",
                                    "modelos",
                                    "2019",
                                    "2022",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Manija apertura exterior puerta delantero derecho",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        self.assertEqual(report["parts"][0]["matches"], [])

    def test_build_quote_match_report_returns_multiple_valid_plumilla_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "parrales"
            (provider_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Parrales",
                        "website": "https://example.invalid/parrales",
                        "matching": {"notes": "Public catalog."},
                        "data_precision": {"reference_codes": True},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "product_name": "PLUMILLA 16 PULG METALICA JGOX2",
                                "product_url": "https://example.invalid/plumilla-16",
                                "category_name": "Plumillas Limpiaparabrisas",
                                "brand": "HELLA",
                                "searchable_tokens": ["plumilla", "16", "pulg", "metalica", "jgox2"],
                            },
                            {
                                "product_name": "PLUMILLA 20 PULG AERODINAMICA CO- N 8 ADAPTADORES 1PCS",
                                "product_url": "https://example.invalid/plumilla-20",
                                "category_name": "Plumillas Limpiaparabrisas",
                                "brand": "KTC",
                                "searchable_tokens": ["plumilla", "20", "pulg", "aerodinamica", "adaptadores"],
                            },
                            {
                                "product_name": "PLUMILLA AEROD. 22 PULG JGOX2",
                                "product_url": "https://example.invalid/plumilla-22",
                                "category_name": "Plumillas Limpiaparabrisas",
                                "brand": "VEKTRA",
                                "searchable_tokens": ["plumilla", "22", "pulg", "aerod", "jgox2"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Plumilla limpiavidrio panoramico trasero",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertEqual(len(matches), 3)
        self.assertEqual(
            {match["detail_url"] for match in matches},
            {
                "https://example.invalid/plumilla-16",
                "https://example.invalid/plumilla-20",
                "https://example.invalid/plumilla-22",
            },
        )

    def test_build_quote_match_report_returns_multiple_valid_bujia_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "parrales"
            (provider_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Parrales",
                        "website": "https://example.invalid/parrales",
                        "matching": {"notes": "Public catalog."},
                        "data_precision": {"reference_codes": True},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "product_name": "BUJIA ENCENDIDO (BKR5ES)",
                                "product_url": "https://example.invalid/bujia-1",
                                "category_name": "Repuestos Electricos",
                                "brand": "NGK",
                                "searchable_tokens": ["bujia", "encendido", "bkr5es"],
                            },
                            {
                                "product_name": "BUJIA ENCENDIDO (BM6A)",
                                "product_url": "https://example.invalid/bujia-2",
                                "category_name": "Repuestos Electricos",
                                "brand": "NGK",
                                "searchable_tokens": ["bujia", "encendido", "bm6a"],
                            },
                            {
                                "product_name": "BUJIA ENCENDIDO (BPR5ES-11)",
                                "product_url": "https://example.invalid/bujia-3",
                                "category_name": "Repuestos Electricos",
                                "brand": "NGK",
                                "searchable_tokens": ["bujia", "encendido", "bpr5es", "11"],
                            },
                            {
                                "product_name": "BOBINA ENCENDIDO",
                                "product_url": "https://example.invalid/bobina",
                                "category_name": "Repuestos Electricos",
                                "brand": "NGK",
                                "searchable_tokens": ["bobina", "encendido"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Bujias",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertEqual(len(matches), 3)
        self.assertTrue(all("BUJIA" in match["product_name"] for match in matches))

    def test_build_quote_match_report_rejects_impocali_filtration_for_kit_plumillas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            impocali_dir = root / "impocali"
            parrales_dir = root / "parrales"
            (impocali_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (parrales_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (impocali_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Impocali",
                        "website": "https://example.invalid/impocali",
                        "matching": {"notes": "Category only."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (parrales_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Parrales",
                        "website": "https://example.invalid/parrales",
                        "matching": {"notes": "Public catalog."},
                        "data_precision": {"reference_codes": True},
                    }
                ),
                encoding="utf-8",
            )
            (impocali_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "segment": "autos",
                                "category_name": "Filtracion",
                                "category_url": "https://example.invalid/filtracion",
                                "taxonomy": "filters",
                                "product_names": ["Filtros de combustible", "Filtros de aire"],
                            },
                            {
                                "segment": "autos",
                                "category_name": "Visibilidad",
                                "category_url": "https://example.invalid/visibilidad",
                                "taxonomy": "wipers_visibility",
                                "product_names": ["Plumillas"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (parrales_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "product_name": "PLUMILLA AEROD. 20 PULG JGOX2",
                                "product_url": "https://example.invalid/kit-plumilla",
                                "category_name": "Plumillas Limpiaparabrisas",
                                "brand": "HELLA",
                                "searchable_tokens": ["plumilla", "20", "pulg", "jgox2"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Kit plumillas",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertTrue(matches)
        self.assertTrue(all("Filtro" not in match["product_name"] for match in matches))
        self.assertTrue(all(match["provider_id"] != "impocali" for match in matches))

    def test_build_quote_match_report_rejects_bomba_for_filtro_combustible(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            impocali_dir = root / "impocali"
            disfal_dir = root / "disfal"
            (impocali_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (disfal_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (impocali_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Impocali",
                        "website": "https://example.invalid/impocali",
                        "matching": {"notes": "Category only."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (disfal_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Disfal",
                        "website": "https://example.invalid/disfal",
                        "matching": {"notes": "Category only."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (impocali_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "segment": "autos",
                                "category_name": "Filtracion",
                                "category_url": "https://example.invalid/filtro-combustible",
                                "taxonomy": "filters",
                                "product_names": ["Filtros de combustible"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (disfal_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "service_families": [
                            {
                                "family_name": "Bomba de combustible",
                                "family_url": "https://example.invalid/bomba-combustible",
                            }
                        ],
                        "service_series": [],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Filtro de combustible",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertTrue(matches)
        self.assertTrue(all("Bomba de combustible" != match["product_name"] for match in matches))
        self.assertEqual(matches[0]["product_name"], "Filtros de combustible")

    def test_build_quote_match_report_dedupes_repeated_provider_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "impocali"
            (provider_dir / "snapshots" / "2026-06-11").mkdir(parents=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(
                    {
                        "display_name": "Impocali",
                        "website": "https://example.invalid/impocali",
                        "matching": {"notes": "Category only."},
                        "data_precision": {"reference_codes": False},
                    }
                ),
                encoding="utf-8",
            )
            (provider_dir / "snapshots" / "2026-06-11" / "extracted.json").write_text(
                json.dumps(
                    {
                        "snapshot_date": "2026-06-11",
                        "products": [
                            {
                                "segment": "autos",
                                "category_name": "Filtracion",
                                "category_url": "https://example.invalid/filtracion-autos",
                                "taxonomy": "filters",
                                "product_names": ["Filtros de combustible"],
                            },
                            {
                                "segment": "carga_y_pasajeros",
                                "category_name": "Filtracion",
                                "category_url": "https://example.invalid/filtracion-carga",
                                "taxonomy": "filters",
                                "product_names": ["Filtros de combustible"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = load_provider_catalog_index(root)

        report = build_quote_match_report(
            quote_payload={
                "orbika": {
                    "marca": "KIA",
                    "linea": "SPORTAGE [4]",
                    "version": "VIBRANT TP 2000CC 2AB ABS CT",
                    "parts": [
                        {
                            "name": "Filtro de combustible",
                            "reference": None,
                            "quantity": 1,
                        }
                    ],
                }
            },
            index=index,
            limit_per_part=5,
        )

        matches = report["parts"][0]["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["product_name"], "Filtros de combustible")

    def test_rebuild_daily_reports_groups_by_received_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            quotes_dir = Path(tmpdir) / "quotes"
            quotes_dir.mkdir()
            daily_dir = Path(tmpdir) / "daily"
            payload = enrich_quote_payload(
                {
                    "quote_key": "quote-1",
                    "generated_at": "2026-06-09T22:00:00+00:00",
                    "source": {
                        "received_at": "2026-06-09T13:19:48+00:00",
                        "subject": "LRX263",
                    },
                    "orbika": {"parts": []},
                },
                index=load_provider_catalog_index(Path(tmpdir)),
                limit_per_part=3,
            )
            (quotes_dir / "quote-1.json").write_text(json.dumps(payload), encoding="utf-8")

            written = rebuild_daily_reports(quotes_dir, daily_dir)

            self.assertEqual(len(written), 2)
            self.assertTrue((daily_dir / "2026-06-09.json").exists())
            self.assertTrue((daily_dir / "2026-06-09.md").exists())


if __name__ == "__main__":
    unittest.main()
