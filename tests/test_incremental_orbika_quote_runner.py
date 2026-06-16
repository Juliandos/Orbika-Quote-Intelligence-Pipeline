import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tools.gmail_quote_extractor import ExtractedMessage
from tools.incremental_orbika_quote_runner import (
    build_gmail_sender_query,
    load_state,
    parse_args,
    quote_key,
    reconcile_state,
    update_completed_cursor,
    write_quote_output,
)
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

    def test_parse_args_enables_login_fallback_explicitly(self) -> None:
        args = parse_args(
            [
                "--credentials",
                "/tmp/client-secret.json",
                "--allow-login-fallback",
            ]
        )
        self.assertTrue(args.allow_login_fallback)

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
