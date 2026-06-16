import base64
import unittest

from tools.gmail_quote_extractor import (
    TARGET_SENDER,
    extract_message,
    extract_quote_urls_from_html,
    extract_quote_url_from_html,
    is_orbika_quote_url,
)


def gmail_body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


class GmailQuoteExtractorTests(unittest.TestCase):
    def test_extracts_exact_cotizar_aviso_href_from_html(self) -> None:
        html = """
        <html>
          <body>
            <a href="https://example.invalid/other">Other</a>
            <a href="https://quotes.example.invalid/path?token=secret"> Cotizar aviso </a>
          </body>
        </html>
        """

        quote_url, audit_excerpt, warnings = extract_quote_url_from_html(html)

        self.assertEqual(quote_url, "https://quotes.example.invalid/path?token=secret")
        self.assertIn("Cotizar aviso", audit_excerpt)
        self.assertIn("token=&lt;redacted&gt;", audit_excerpt)
        self.assertEqual(warnings, [])

    def test_extracts_multiple_unique_cotizar_aviso_hrefs_from_html(self) -> None:
        html = """
        <a href="https://quotes.example.invalid/1">Cotizar aviso</a>
        <a href="https://quotes.example.invalid/1">Cotizar aviso</a>
        <a href="https://quotes.example.invalid/2">Cotizar aviso</a>
        """

        quote_urls, audit_excerpt, warnings = extract_quote_urls_from_html(html)

        self.assertEqual(
            quote_urls,
            [
                "https://quotes.example.invalid/1",
                "https://quotes.example.invalid/2",
            ],
        )
        self.assertIn("Cotizar aviso", audit_excerpt)
        self.assertEqual(warnings, [])

    def test_extract_message_rejects_unexpected_sender(self) -> None:
        message = {
            "id": "gmail-1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Someone <other@example.invalid>"},
                    {"name": "Subject", "value": "Quote"},
                ],
                "body": {"data": gmail_body('<a href="https://example.invalid">Cotizar aviso</a>')},
                "mimeType": "text/html",
            },
        }

        record = extract_message(message)

        self.assertEqual(record.extraction_status, "sender_mismatch")
        self.assertIsNone(record.quote_url)
        self.assertEqual(record.gmail_id, "gmail-1")
        self.assertEqual(record.quote_urls, [])

    def test_extract_message_returns_link_not_found_without_html_match(self) -> None:
        message = {
            "id": "gmail-2",
            "internalDate": "1798747200000",
            "payload": {
                "headers": [
                    {"name": "From", "value": f"Orbika <{TARGET_SENDER}>"},
                    {"name": "Subject", "value": "Quote"},
                ],
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": gmail_body("<p>No target button here</p>")},
                    }
                ],
            },
        }

        record = extract_message(message)

        self.assertEqual(record.extraction_status, "link_not_found")
        self.assertIsNone(record.quote_url)
        self.assertTrue(any("selector fallback" in warning for warning in record.warnings))

    def test_discards_marketplace_anchor_and_requires_external_quote(self) -> None:
        html = """
        <a href="https://orbika.subocol.com/web/guest/marketplace">Cotizar aviso</a>
        """

        quote_urls, audit_excerpt, warnings = extract_quote_urls_from_html(html)

        self.assertEqual(quote_urls, [])
        self.assertIn("Cotizar aviso", audit_excerpt)
        self.assertTrue(any("marketplace" in warning.lower() for warning in warnings))
        self.assertFalse(is_orbika_quote_url("https://orbika.subocol.com/web/guest/marketplace"))


if __name__ == "__main__":
    unittest.main()
