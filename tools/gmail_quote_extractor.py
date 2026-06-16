#!/usr/bin/env python3
"""Read-only Gmail quote link extractor for Orbika quotation emails."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


AUTHORIZED_ACCOUNT = "autolujoslaser1@gmail.com"
TARGET_SENDER = "cotizacionesorbika@subocol.com"
TARGET_LINK_TEXT = "Cotizar aviso"
OBSERVED_GMAIL_SELECTOR = (
    "#avWBGd-182 > div:nth-child(2) > div:nth-child(1) > div:nth-child(3) > "
    "table > tbody > tr > td > div > table > tbody > tr > td > table > tbody > "
    "tr > td > a"
)
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_OUTPUT_DIR = Path("local/gmail_quote_extractor")
DEFAULT_TOKEN_PATH = (
    Path.home()
    / ".cache"
    / "openclaw"
    / "gmail_quote_extractor"
    / "autolujoslaser1-token.json"
)


@dataclass
class ExtractedMessage:
    message_id: str
    gmail_id: str
    internal_date_ms: str | None
    sender: str
    subject: str
    received_at: str
    quote_url: str | None
    audit_excerpt: str
    extraction_status: str
    quote_urls: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class AnchorTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current_anchor: dict[str, Any] | None = None
        self.anchors: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        self._current_anchor = {
            "href": attr_map.get("href", ""),
            "text_parts": [],
            "attrs": attr_map,
        }

    def handle_data(self, data: str) -> None:
        if self._current_anchor is not None:
            self._current_anchor["text_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_anchor is None:
            return
        attrs = self._current_anchor["attrs"]
        self.anchors.append(
            {
                "href": self._current_anchor["href"],
                "text": normalize_text("".join(self._current_anchor["text_parts"])),
                "title": normalize_text(attrs.get("title", "")),
                "aria_label": normalize_text(attrs.get("aria-label", "")),
            }
        )
        self._current_anchor = None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def is_orbika_quote_url(value: str | None) -> bool:
    if not value:
        return False
    parts = urlsplit(str(value).strip())
    return (
        parts.scheme in {"http", "https"}
        and parts.netloc.lower() == "orbika.subocol.com"
        and parts.path.lower() == "/web/guest/external/quote"
        and bool(parts.query)
    )


def is_orbika_marketplace_url(value: str | None) -> bool:
    if not value:
        return False
    parts = urlsplit(str(value).strip())
    return (
        parts.scheme in {"http", "https"}
        and parts.netloc.lower() == "orbika.subocol.com"
        and parts.path.lower() == "/web/guest/marketplace"
    )


def mask_url(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(r"([?&][^=&]+)=([^&]+)", r"\1=<redacted>", value)


def is_path_inside_repo(path: Path, repo_root: Path) -> bool:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return True


def reject_repo_secret_path(path: Path, repo_root: Path, label: str) -> None:
    if is_path_inside_repo(path.expanduser(), repo_root):
        raise SystemExit(
            f"{label} must not be stored inside the repository: {path}. "
            "Use a path outside the repo, for example under ~/.config or ~/.cache."
        )


def extract_quote_urls_from_html(html: str) -> tuple[list[str], str, list[str]]:
    parser = AnchorTextParser()
    parser.feed(html)
    warnings: list[str] = []

    def extract_valid_quote_urls(anchors: list[dict[str, str]]) -> tuple[list[str], list[str]]:
        valid_urls = dedupe_urls(
            anchor["href"]
            for anchor in anchors
            if is_orbika_quote_url(anchor["href"])
        )
        invalid_marketplace_urls = dedupe_urls(
            anchor["href"]
            for anchor in anchors
            if is_orbika_marketplace_url(anchor["href"])
        )
        return valid_urls, invalid_marketplace_urls

    exact_matches = [
        anchor
        for anchor in parser.anchors
        if anchor["text"] == TARGET_LINK_TEXT and anchor["href"]
    ]
    if exact_matches:
        valid_urls, invalid_marketplace_urls = extract_valid_quote_urls(exact_matches)
        if valid_urls:
            if invalid_marketplace_urls:
                warnings.append(
                    "Ignored Orbika marketplace link(s) and kept only external quote link(s)."
                )
            return (
                valid_urls,
                build_anchor_audit_excerpt(exact_matches[0]),
                warnings,
            )
        if invalid_marketplace_urls:
            warnings.append(
                "Found 'Cotizar aviso' anchor(s) pointing to Orbika marketplace instead of external quote."
            )
            return [], build_anchor_audit_excerpt(exact_matches[0]), warnings
        return (
            dedupe_urls(anchor["href"] for anchor in exact_matches),
            build_anchor_audit_excerpt(exact_matches[0]),
            warnings,
        )

    metadata_matches = [
        anchor
        for anchor in parser.anchors
        if TARGET_LINK_TEXT in {anchor["title"], anchor["aria_label"]} and anchor["href"]
    ]
    if metadata_matches:
        valid_urls, invalid_marketplace_urls = extract_valid_quote_urls(metadata_matches)
        if valid_urls:
            warnings.append("Matched target link text from anchor metadata instead of visible text.")
            if invalid_marketplace_urls:
                warnings.append(
                    "Ignored Orbika marketplace link(s) and kept only external quote link(s)."
                )
            return (
                valid_urls,
                build_anchor_audit_excerpt(metadata_matches[0]),
                warnings,
            )
        if invalid_marketplace_urls:
            warnings.append("Matched target link text from anchor metadata instead of visible text.")
            warnings.append(
                "Found metadata-matched Orbika marketplace link(s) instead of external quote."
            )
            return [], build_anchor_audit_excerpt(metadata_matches[0]), warnings
        warnings.append("Matched target link text from anchor metadata instead of visible text.")
        return (
            dedupe_urls(anchor["href"] for anchor in metadata_matches),
            build_anchor_audit_excerpt(metadata_matches[0]),
            warnings,
        )

    warnings.append("No anchor with visible text 'Cotizar aviso' was found in the email HTML.")
    return [], "", warnings


def extract_quote_url_from_html(html: str) -> tuple[str | None, str, list[str]]:
    quote_urls, audit_excerpt, warnings = extract_quote_urls_from_html(html)
    return (quote_urls[0] if quote_urls else None), audit_excerpt, warnings


def dedupe_urls(values: Any) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def build_anchor_audit_excerpt(anchor: dict[str, str]) -> str:
    href = escape(mask_url(anchor.get("href")) or "")
    text = escape(anchor.get("text") or "")
    return f'<a href="{href}">{text}</a>'


def decode_body_data(data: str | None) -> str:
    if not data:
        return ""
    padded = data + ("=" * (-len(data) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def collect_payload_bodies(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    html_parts: list[str] = []
    text_parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if mime_type == "text/html":
            html_parts.append(decode_body_data(body_data))
        elif mime_type == "text/plain":
            text_parts.append(decode_body_data(body_data))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return html_parts, text_parts


def header_value(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def normalize_sender(sender_header: str) -> str:
    match = re.search(r"<([^>]+)>", sender_header)
    if match:
        return match.group(1).strip().lower()
    return sender_header.strip().lower()


def normalize_received_at(date_header: str, internal_date_ms: str | None) -> str:
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    if internal_date_ms:
        return datetime.fromtimestamp(int(internal_date_ms) / 1000, timezone.utc).isoformat()
    return ""


def extract_message(message: dict[str, Any]) -> ExtractedMessage:
    payload = message.get("payload", {})
    headers = payload.get("headers", []) or []
    message_id = header_value(headers, "Message-ID") or message.get("id", "")
    gmail_id = message.get("id", "")
    internal_date_ms = message.get("internalDate")
    sender_header = header_value(headers, "From")
    sender = normalize_sender(sender_header)
    subject = header_value(headers, "Subject")
    received_at = normalize_received_at(header_value(headers, "Date"), internal_date_ms)
    warnings: list[str] = []

    if sender != TARGET_SENDER:
        warnings.append(f"Skipped unexpected sender: {sender_header}")
        return ExtractedMessage(
            message_id=message_id,
            gmail_id=gmail_id,
            internal_date_ms=internal_date_ms,
            sender=sender_header,
            subject=subject,
            received_at=received_at,
            quote_url=None,
            quote_urls=[],
            audit_excerpt="",
            extraction_status="sender_mismatch",
            warnings=warnings,
        )

    html_parts, text_parts = collect_payload_bodies(payload)
    for html in html_parts:
        quote_urls, audit_excerpt, html_warnings = extract_quote_urls_from_html(html)
        warnings.extend(html_warnings)
        if quote_urls:
            return ExtractedMessage(
                message_id=message_id,
                gmail_id=gmail_id,
                internal_date_ms=internal_date_ms,
                sender=sender_header,
                subject=subject,
                received_at=received_at,
                quote_url=quote_urls[0],
                quote_urls=quote_urls,
                audit_excerpt=audit_excerpt,
                extraction_status="extracted",
                warnings=warnings,
            )

    audit_excerpt = normalize_text(" ".join(text_parts))[:500]
    if html_parts and not audit_excerpt:
        audit_excerpt = "HTML message inspected; target anchor was not found."
    warnings.append(
        "Browser or Gmail selector fallback was not executed in phase 1; "
        f"observed selector retained for manual fallback: {OBSERVED_GMAIL_SELECTOR}"
    )
    return ExtractedMessage(
        message_id=message_id,
        gmail_id=gmail_id,
        internal_date_ms=internal_date_ms,
        sender=sender_header,
        subject=subject,
        received_at=received_at,
        quote_url=None,
        quote_urls=[],
        audit_excerpt=audit_excerpt,
        extraction_status="link_not_found",
        warnings=warnings,
    )


def get_gmail_service(credentials_path: Path, token_path: Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit(
            "Missing Gmail API dependencies. Run with "
            "`uv run --with google-api-python-client --with google-auth-oauthlib python ...`."
        ) from exc

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), [GMAIL_READONLY_SCOPE])

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not credentials_path.exists():
                raise SystemExit(f"OAuth client secrets file not found: {credentials_path}")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                scopes=[GMAIL_READONLY_SCOPE],
            )
            credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        token_path.chmod(0o600)

    return build("gmail", "v1", credentials=credentials)


def verify_authorized_account(service: Any) -> None:
    profile = service.users().getProfile(userId="me").execute()
    email_address = profile.get("emailAddress", "").lower()
    if email_address != AUTHORIZED_ACCOUNT:
        raise SystemExit(
            f"Authenticated Gmail account is {email_address!r}; expected {AUTHORIZED_ACCOUNT!r}."
        )


def iter_gmail_messages(service: Any, max_results: int) -> list[dict[str, Any]]:
    query = f"from:{TARGET_SENDER}"
    return iter_gmail_messages_with_query(service, query=query, max_results=max_results)


def iter_gmail_messages_with_query(service: Any, query: str, max_results: int) -> list[dict[str, Any]]:
    remaining = max_results
    page_token = None
    message_refs: list[dict[str, Any]] = []
    while remaining > 0:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=min(remaining, 500),
                pageToken=page_token,
            )
            .execute()
        )
        messages = response.get("messages", []) or []
        message_refs.extend(messages)
        remaining -= len(messages)
        page_token = response.get("nextPageToken")
        if not messages or not page_token:
            break

    full_messages: list[dict[str, Any]] = []
    for message in message_refs:
        full_messages.append(
            service.users()
            .messages()
            .get(
                userId="me",
                id=message["id"],
                format="full",
            )
            .execute()
        )
    return full_messages


def write_json(path: Path, records: list[ExtractedMessage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authorized_account": AUTHORIZED_ACCOUNT,
        "target_sender": TARGET_SENDER,
        "target_link_text": TARGET_LINK_TEXT,
        "records": [asdict(record) for record in records],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, records: list[ExtractedMessage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "message_id",
                "gmail_id",
                "internal_date_ms",
                "sender",
                "subject",
                "received_at",
                "quote_url",
                "quote_urls",
                "audit_excerpt",
                "extraction_status",
                "warnings",
            ],
        )
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["quote_urls"] = " | ".join(record.quote_urls)
            row["warnings"] = " | ".join(record.warnings)
            writer.writerow(row)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract 'Cotizar aviso' quote links from authorized Gmail messages in read-only mode."
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path(os.environ.get("GMAIL_OAUTH_CLIENT_SECRET", "")).expanduser()
        if os.environ.get("GMAIL_OAUTH_CLIENT_SECRET")
        else None,
        help="OAuth client secrets JSON path outside the repo. Can also use GMAIL_OAUTH_CLIENT_SECRET.",
    )
    parser.add_argument(
        "--token-cache",
        type=Path,
        default=DEFAULT_TOKEN_PATH,
        help=f"OAuth token cache path outside the repo. Default: {DEFAULT_TOKEN_PATH}",
    )
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "quotes.json",
        help="Local JSON output path. Default is gitignored.",
    )
    parser.add_argument("--csv-output", type=Path, default=None, help="Optional CSV output path.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = Path.cwd()

    if args.credentials is None:
        raise SystemExit("Provide --credentials or GMAIL_OAUTH_CLIENT_SECRET.")
    reject_repo_secret_path(args.credentials, repo_root, "OAuth client secrets")
    reject_repo_secret_path(args.token_cache, repo_root, "OAuth token cache")

    service = get_gmail_service(args.credentials.expanduser(), args.token_cache.expanduser())
    verify_authorized_account(service)
    messages = iter_gmail_messages(service, args.max_results)
    records = [extract_message(message) for message in messages]

    write_json(args.json_output, records)
    if args.csv_output:
        write_csv(args.csv_output, records)

    extracted = sum(1 for record in records if record.extraction_status == "extracted")
    print(
        f"Processed {len(records)} message(s) from {TARGET_SENDER}; "
        f"extracted {extracted} quote link(s). Output: {args.json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
