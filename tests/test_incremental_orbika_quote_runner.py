import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tools.gmail_quote_extractor import ExtractedMessage
from tools.incremental_orbika_quote_runner import (
    DEFAULT_DAILY_REPORT_DIR,
    DEFAULT_QUOTES_DIR,
    DEFAULT_SNAPSHOT_DIR,
    add_agentic_review_to_quote_payload,
    build_gmail_sender_query,
    build_quote_output_payload,
    format_poll_status,
    load_state,
    parse_args,
    persist_quote_output_to_postgres,
    quote_key,
    reconcile_state,
    update_completed_cursor,
    write_quote_output,
)
from tools.agentic_match_reviewer import DEFAULT_TRACE_DIR
from tools.orbika_quote_extractor import ExtractedPart, ExtractedQuote


class IncrementalOrbikaQuoteRunnerTests(unittest.TestCase):
    def test_build_gmail_sender_query_without_date(self) -> None:
        self.assertIn("from:cotizacionesorbika@subocol.com", build_gmail_sender_query())

    def test_build_gmail_sender_query_for_single_day(self) -> None:
        query = build_gmail_sender_query(date(2026, 6, 14))
        self.assertEqual(
            query,
            "from:cotizacionesorbika@subocol.com after:2026/06/14 before:2026/06/15",
        )

    def test_parse_args_disables_login_fallback_by_default(self) -> None:
        args = parse_args(["--credentials", "/tmp/client-secret.json"])
        self.assertFalse(args.allow_login_fallback)
        self.assertIsNone(args.gmail_date)
        self.assertFalse(args.skip_agentic_review)
        self.assertEqual(args.file_output_mode, "minimal")
        self.assertEqual(args.quotes_dir, DEFAULT_QUOTES_DIR)
        self.assertEqual(args.daily_report_dir, DEFAULT_DAILY_REPORT_DIR)
        self.assertIsNone(args.agentic_trace_dir)
        self.assertIsNone(args.snapshot_dir)

    def test_parse_args_enables_login_fallback_explicitly(self) -> None:
        args = parse_args(
            [
                "--credentials",
                "/tmp/client-secret.json",
                "--allow-login-fallback",
            ]
        )
        self.assertTrue(args.allow_login_fallback)

    def test_parse_args_can_skip_agentic_review(self) -> None:
        args = parse_args(
            [
                "--credentials",
                "/tmp/client-secret.json",
                "--skip-agentic-review",
            ]
        )
        self.assertTrue(args.skip_agentic_review)

    def test_parse_args_standard_mode_enables_agentic_traces(self) -> None:
        args = parse_args(
            [
                "--credentials",
                "/tmp/client-secret.json",
                "--file-output-mode",
                "standard",
            ]
        )
        self.assertEqual(args.agentic_trace_dir, DEFAULT_TRACE_DIR)
        self.assertIsNone(args.snapshot_dir)

    def test_parse_args_debug_mode_enables_snapshots(self) -> None:
        args = parse_args(
            [
                "--credentials",
                "/tmp/client-secret.json",
                "--file-output-mode",
                "debug",
            ]
        )
        self.assertEqual(args.agentic_trace_dir, DEFAULT_TRACE_DIR)
        self.assertEqual(args.snapshot_dir, DEFAULT_SNAPSHOT_DIR)

    def test_resolve_output_dirs_preserves_explicit_paths(self) -> None:
        args = parse_args(
            [
                "--credentials",
                "/tmp/client-secret.json",
                "--agentic-trace-dir",
                "/tmp/traces",
                "--snapshot-dir",
                "/tmp/snaps",
                "--daily-report-dir",
                "/tmp/daily",
                "--quotes-dir",
                "/tmp/quotes",
            ]
        )
        self.assertEqual(args.agentic_trace_dir, Path("/tmp/traces"))
        self.assertEqual(args.snapshot_dir, Path("/tmp/snaps"))
        self.assertEqual(args.daily_report_dir, Path("/tmp/daily"))
        self.assertEqual(args.quotes_dir, Path("/tmp/quotes"))

    def test_parse_args_accepts_gmail_date(self) -> None:
        args = parse_args(
            [
                "--credentials",
                "/tmp/client-secret.json",
                "--gmail-date",
                "2026-06-14",
            ]
        )
        self.assertEqual(args.gmail_date, date(2026, 6, 14))

    def test_persist_quote_output_to_postgres_skips_without_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "quote.json"
            path.write_text(json.dumps({"quote_key": "quote-key"}), encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                result = persist_quote_output_to_postgres(path)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "missing_database_url")

    def test_format_poll_status_includes_postgres_counts(self) -> None:
        state = load_state(Path("/tmp/nonexistent-openclaw-state.json"))
        status = format_poll_status(
            state,
            {
                "messages_seen": 1,
                "quotes_processed": 1,
                "quotes_skipped": 0,
                "quotes_postgres_persisted": 1,
                "quotes_postgres_updated": 0,
                "quotes_postgres_failed": 0,
                "quotes_postgres_skipped": 0,
            },
            poll_seconds=0,
        )

        self.assertIn("postgres persisted=1", status)

    def test_load_state_creates_resume_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = load_state(Path(tmpdir) / "state.json")

        self.assertEqual(state["version"], 2)
        self.assertEqual(state["current"]["stage"], "idle")
        self.assertIsNone(state["cursor"]["last_completed_internal_date_ms"])
        self.assertEqual(state["messages"], {})
        self.assertEqual(state["quotes"], {})

    def test_load_state_migrates_previous_state_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text(json.dumps({"version": 1, "messages": {}, "quotes": {}}), encoding="utf-8")
            state = load_state(path)

        self.assertEqual(state["version"], 1)
        self.assertEqual(state["current"]["stage"], "idle")
        self.assertIn("last_completed_internal_date_ms", state["cursor"])

    def test_update_completed_cursor_keeps_highest_completed_message(self) -> None:
        state = load_state(Path("/tmp/nonexistent-openclaw-state.json"))

        update_completed_cursor(state, "gmail-1", "100")
        update_completed_cursor(state, "gmail-older", "50")
        update_completed_cursor(state, "gmail-2", "200")

        self.assertEqual(state["cursor"]["last_completed_internal_date_ms"], "200")
        self.assertEqual(state["cursor"]["last_completed_gmail_id"], "gmail-2")

    def test_quote_key_is_stable_and_url_specific(self) -> None:
        first = quote_key("<message-1>", "https://quotes.example.invalid/1")
        second = quote_key("<message-1>", "https://quotes.example.invalid/1")
        third = quote_key("<message-1>", "https://quotes.example.invalid/2")

        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertEqual(len(first), 24)

    def test_write_quote_output_creates_individual_quote_file(self) -> None:
        message = ExtractedMessage(
            message_id="<message-1>",
            gmail_id="gmail-1",
            internal_date_ms="1798747200000",
            sender="Orbika <cotizacionesorbika@subocol.com>",
            subject="Quote",
            received_at="2026-12-31T12:00:00+00:00",
            quote_url="https://quotes.example.invalid/1?token=secret",
            quote_urls=["https://quotes.example.invalid/1?token=secret"],
            audit_excerpt="",
            extraction_status="extracted",
        )
        quote = ExtractedQuote(
            quote_url="https://quotes.example.invalid/1?token=secret",
            load_status="loaded",
            retries_used=0,
            aviso_id="428482",
            fecha_aviso=None,
            marca=None,
            linea=None,
            version=None,
            ano=None,
            placa=None,
            vin=None,
            taller_entrega=None,
            nombre_comercial=None,
            nit=None,
            ciudad=None,
            direccion=None,
            telefono=None,
            email=None,
            repuestos_count=1,
            total_cotizacion=None,
            repuestos_cotizados=None,
            parts=[
                ExtractedPart(
                    name="Capo",
                    reference="664003W001",
                    reference_input_value="664003W001",
                    reference_button_text="664003W001",
                    reference_source="button_text",
                    reference_validation_text="Codigo validado",
                    reference_validation_visible=True,
                    quantity=1,
                    unit_gross_price="$10.000",
                    delivery_days="3",
                    discount="5",
                    quality="GENUINO",
                    total_value="$19.000",
                    observation_visible="Agregar observacion",
                    rejected_button_present=True,
                    raw_status="loaded",
                    visible_dom_values={
                        "reference": "664003W001",
                        "quantity": "1",
                    },
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = write_quote_output(
                quotes_dir=Path(tmpdir),
                key="quote-key",
                message_record=message,
                quote_url=message.quote_url or "",
                quote_record=quote,
                supplier_matching={
                    "summary": {
                        "parts_total": 0,
                        "parts_with_matches": 0,
                    }
                },
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["quote_key"], "quote-key")
        self.assertEqual(payload["source"]["gmail_id"], "gmail-1")
        self.assertEqual(payload["orbika"]["aviso_id"], "428482")
        self.assertIn("<redacted>", payload["quote_url_masked"])
        self.assertIn("supplier_matching", payload)
        self.assertNotIn("quote_url", payload["orbika"])
        self.assertNotIn("visible_dom_values", payload["orbika"]["parts"][0])
        self.assertNotIn("reference_input_value", payload["orbika"]["parts"][0])
        self.assertEqual(payload["orbika"]["parts"][0]["reference"], "664003W001")
        self.assertEqual(payload["orbika"]["parts"][0]["quantity"], 1)
        self.assertNotIn("provider_snapshot_dates", payload["supplier_matching"])

    def test_add_agentic_review_to_quote_payload_returns_review_and_trace(self) -> None:
        message = ExtractedMessage(
            message_id="<message-1>",
            gmail_id="gmail-1",
            internal_date_ms="1798747200000",
            sender="Orbika <cotizacionesorbika@subocol.com>",
            subject="Quote",
            received_at="2026-12-31T12:00:00+00:00",
            quote_url="https://quotes.example.invalid/1",
            quote_urls=["https://quotes.example.invalid/1"],
            audit_excerpt="",
            extraction_status="extracted",
        )
        quote = ExtractedQuote(
            quote_url="https://quotes.example.invalid/1",
            load_status="loaded",
            retries_used=0,
            aviso_id="428482",
            fecha_aviso=None,
            marca="KIA",
            linea="SPORTAGE",
            version="VIBRANT",
            ano=None,
            placa=None,
            vin=None,
            taller_entrega=None,
            nombre_comercial=None,
            nit=None,
            ciudad=None,
            direccion=None,
            telefono=None,
            email=None,
            repuestos_count=0,
            total_cotizacion=None,
            repuestos_cotizados=None,
            parts=[],
        )
        payload = build_quote_output_payload(
            key="quote-key",
            message_record=message,
            quote_url=message.quote_url or "",
            quote_record=quote,
            supplier_matching={
                "generated_at": "2026-06-18T00:00:00+00:00",
                "parts": [
                    {
                        "part_name": "Protector motor",
                        "requested_reference": None,
                        "matches": [
                            {
                                "provider_id": "partcar",
                                "provider_name": "Partcar",
                                "score_percent": 80,
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
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            agentic_matching, trace_path = add_agentic_review_to_quote_payload(
                payload,
                trace_dir=Path(tmpdir),
                limit_per_part=3,
                model_name=None,
            )
            self.assertIsNotNone(trace_path)
            self.assertTrue(trace_path.exists())

        self.assertIsNotNone(agentic_matching)
        self.assertEqual(agentic_matching["summary"]["parts_reviewed"], 1)

    def test_reconcile_state_refreshes_cursor_and_clears_stale_current(self) -> None:
        state = {
            "cursor": {
                "last_completed_internal_date_ms": "1",
                "last_completed_gmail_id": "old",
            },
            "current": {
                "gmail_id": "gmail-2",
                "quote_key": "quote-2",
                "stage": "fetching_orbika_quote",
            },
            "messages": {
                "gmail-1": {"status": "completed", "internal_date_ms": "100"},
                "gmail-2": {"status": "completed", "internal_date_ms": "200"},
            },
            "quotes": {
                "quote-2": {"status": "processed"},
            },
            "last_run": {},
        }

        reconcile_state(state)

        self.assertEqual(state["cursor"]["last_completed_internal_date_ms"], "200")
        self.assertEqual(state["cursor"]["last_completed_gmail_id"], "gmail-2")
        self.assertEqual(state["current"]["stage"], "idle")

    def test_reconcile_state_invalidates_marketplace_quote_resume(self) -> None:
        state = {
            "cursor": {
                "last_completed_internal_date_ms": None,
                "last_completed_gmail_id": None,
            },
            "current": {
                "gmail_id": "gmail-1",
                "quote_key": "quote-1",
                "stage": "fetching_orbika_quote",
            },
            "messages": {
                "gmail-1": {"status": "in_progress", "internal_date_ms": "100"},
            },
            "quotes": {
                "quote-1": {
                    "status": "in_progress",
                    "quote_url_masked": "https://orbika.subocol.com/web/guest/marketplace",
                }
            },
            "last_run": {},
        }

        reconcile_state(state)

        self.assertEqual(state["current"]["stage"], "idle")
        self.assertEqual(state["quotes"]["quote-1"]["status"], "invalid_quote_url")
        self.assertIn("marketplace", state["quotes"]["quote-1"]["last_error"].lower())


if __name__ == "__main__":
    unittest.main()
