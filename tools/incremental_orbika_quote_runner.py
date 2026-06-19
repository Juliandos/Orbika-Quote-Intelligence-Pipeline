#!/usr/bin/env python3
"""Incremental read-only Gmail to Orbika quote processor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.gmail_quote_extractor import (
    DEFAULT_TOKEN_PATH,
    TARGET_SENDER,
    extract_message,
    get_gmail_service,
    is_orbika_quote_url,
    iter_gmail_messages_with_query,
    reject_repo_secret_path as reject_gmail_secret_path,
    verify_authorized_account,
)
from tools.orbika_quote_extractor import (
    DEFAULT_STORAGE_STATE,
    fetch_quote_html,
    mask_url,
    parse_orbika_quote_html,
    quote_page_ready,
    reject_repo_secret_path as reject_orbika_secret_path,
)
from tools.agentic_match_reviewer import (
    DEFAULT_TRACE_DIR,
    enrich_quote_payload_with_agentic_review,
    write_trace_file,
)
from tools.postgres_quote_persistence import database_url_from_env, persist_single_quote_file
from tools.supplier_quote_matcher import (
    DEFAULT_DAILY_REPORT_DIR,
    DEFAULT_PROVIDERS_ROOT,
    build_quote_match_report,
    compact_quote_payload_for_storage,
    load_provider_catalog_index,
    rebuild_daily_reports,
)


DEFAULT_OUTPUT_DIR = Path("local/orbika_incremental")
DEFAULT_STATE_PATH = DEFAULT_OUTPUT_DIR / "state.json"
DEFAULT_QUOTES_DIR = DEFAULT_OUTPUT_DIR / "quotes"
DEFAULT_SNAPSHOT_DIR = DEFAULT_OUTPUT_DIR / "snapshots"
FILE_OUTPUT_MODES = ("minimal", "standard", "debug")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def quote_key(message_id: str, quote_url: str) -> str:
    digest = hashlib.sha256(f"{message_id}\n{quote_url}".encode("utf-8")).hexdigest()
    return digest[:24]


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 2,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "target_sender": TARGET_SENDER,
            "cursor": {
                "last_completed_internal_date_ms": None,
                "last_completed_gmail_id": None,
            },
            "current": {
                "gmail_id": None,
                "quote_key": None,
                "stage": "idle",
            },
            "messages": {},
            "quotes": {},
            "last_run": {},
        }
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("version", 1)
    state.setdefault(
        "cursor",
        {
            "last_completed_internal_date_ms": None,
            "last_completed_gmail_id": None,
        },
    )
    state.setdefault(
        "current",
        {
            "gmail_id": None,
            "quote_key": None,
            "stage": "idle",
        },
    )
    state.setdefault("messages", {})
    state.setdefault("quotes", {})
    state.setdefault("last_run", {})
    reconcile_state(state)
    return state


def reconcile_state(state: dict[str, Any]) -> None:
    highest_completed: tuple[int, str] | None = None
    for gmail_id, record in state.get("messages", {}).items():
        if record.get("status") != "completed":
            continue
        internal_date_ms = record.get("internal_date_ms")
        try:
            candidate = (int(internal_date_ms), str(gmail_id))
        except (TypeError, ValueError):
            continue
        if highest_completed is None or candidate > highest_completed:
            highest_completed = candidate
    if highest_completed is not None:
        cursor = state.setdefault("cursor", {})
        cursor["last_completed_internal_date_ms"] = str(highest_completed[0])
        cursor["last_completed_gmail_id"] = highest_completed[1]

    current = state.setdefault("current", {})
    current_gmail_id = current.get("gmail_id")
    current_quote_key = current.get("quote_key")
    current_stage = current.get("stage") or "idle"
    if current_stage == "idle":
        return
    quote_record = state.get("quotes", {}).get(current_quote_key or "")
    message_record = state.get("messages", {}).get(current_gmail_id or "")
    if quote_record and quote_record.get("status") == "processed":
        set_current(state, None, None, "idle")
        return
    if message_record and message_record.get("status") == "completed" and not quote_record:
        set_current(state, None, None, "idle")
        return
    if quote_record and quote_record.get("quote_url_masked") == "https://orbika.subocol.com/web/guest/marketplace":
        set_current(state, None, None, "idle")
        quote_record["status"] = "invalid_quote_url"
        quote_record["last_error"] = "Stored quote URL resolved to Orbika marketplace instead of external quote."
        quote_record["last_error_at"] = utc_now()
        return


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def resolve_output_dirs(args: argparse.Namespace) -> argparse.Namespace:
    if args.quotes_dir is None:
        args.quotes_dir = DEFAULT_QUOTES_DIR

    if args.daily_report_dir is None:
        args.daily_report_dir = DEFAULT_DAILY_REPORT_DIR

    if args.agentic_trace_dir is None:
        args.agentic_trace_dir = DEFAULT_TRACE_DIR if args.file_output_mode in {"standard", "debug"} else None

    if args.snapshot_dir is None:
        args.snapshot_dir = DEFAULT_SNAPSHOT_DIR if args.file_output_mode == "debug" else None

    return args


def build_quote_output_payload(
    *,
    key: str,
    message_record: Any,
    quote_url: str,
    quote_record: Any,
    supplier_matching: dict[str, Any] | None = None,
    agentic_supplier_matching: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "generated_at": utc_now(),
        "quote_key": key,
        "source": {
            "gmail_id": message_record.gmail_id,
            "message_id": message_record.message_id,
            "internal_date_ms": message_record.internal_date_ms,
            "received_at": message_record.received_at,
            "sender": message_record.sender,
            "subject": message_record.subject,
        },
        "quote_url": quote_url,
        "quote_url_masked": mask_url(quote_url),
        "orbika": asdict(quote_record),
    }
    if supplier_matching is not None:
        payload["supplier_matching"] = supplier_matching
    if agentic_supplier_matching is not None:
        payload["agentic_supplier_matching"] = agentic_supplier_matching
    return payload


def write_quote_output(
    quotes_dir: Path,
    key: str,
    message_record: Any,
    quote_url: str,
    quote_record: Any,
    supplier_matching: dict[str, Any] | None = None,
    agentic_supplier_matching: dict[str, Any] | None = None,
) -> Path:
    quotes_dir.mkdir(parents=True, exist_ok=True)
    output_path = quotes_dir / f"{key}.json"
    payload = build_quote_output_payload(
        key=key,
        message_record=message_record,
        quote_url=quote_url,
        quote_record=quote_record,
        supplier_matching=supplier_matching,
        agentic_supplier_matching=agentic_supplier_matching,
    )
    compact_payload = compact_quote_payload_for_storage(payload)
    output_path.write_text(json.dumps(compact_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def add_agentic_review_to_quote_payload(
    quote_payload: dict[str, Any],
    *,
    trace_dir: Path | None,
    limit_per_part: int,
    model_name: str | None,
) -> tuple[dict[str, Any] | None, Path | None]:
    enriched = enrich_quote_payload_with_agentic_review(
        quote_payload,
        limit_per_part=limit_per_part,
        model_name=model_name,
    )
    trace_path = write_trace_file(trace_dir, enriched) if trace_dir else None
    return enriched.get("agentic_supplier_matching"), trace_path


def persist_quote_output_to_postgres(output_path: Path) -> dict[str, Any]:
    database_url = database_url_from_env()
    if not database_url:
        message = "DATABASE_URL is not configured; keeping quote in local files only."
        print(f"warning: {message}", file=sys.stderr)
        return {
            "status": "skipped",
            "reason": "missing_database_url",
            "warning": message,
            "updated_at": utc_now(),
        }

    try:
        counters = persist_single_quote_file(output_path, database_url=database_url)
    except Exception as exc:  # noqa: BLE001 - persistence must not break local flow.
        message = f"PostgreSQL persistence failed for {output_path}: {exc}"
        print(f"warning: {message}", file=sys.stderr)
        return {
            "status": "failed",
            "reason": "postgres_error",
            "warning": message,
            "updated_at": utc_now(),
        }

    status = "failed" if counters.failed else "persisted"
    if counters.warning_messages:
        for warning in counters.warning_messages:
            print(f"warning: postgres persistence: {warning}", file=sys.stderr)
    return {
        "status": status,
        "imported": counters.imported,
        "updated": counters.updated,
        "failed": counters.failed,
        "emails": counters.emails,
        "quotes": counters.quotes,
        "vehicles": counters.vehicles,
        "workshops": counters.workshops,
        "parts": counters.parts,
        "supplier_matches": counters.supplier_matches,
        "agentic_reviews": counters.agentic_reviews,
        "warnings": counters.warning_messages,
        "updated_at": utc_now(),
    }


def message_sort_key(message: dict[str, Any]) -> tuple[int, str]:
    internal_date = message.get("internalDate")
    try:
        return int(internal_date or 0), str(message.get("id", ""))
    except ValueError:
        return 0, str(message.get("id", ""))


def fetch_gmail_message(service: Any, gmail_id: str) -> dict[str, Any]:
    return (
        service.users()
        .messages()
        .get(
            userId="me",
            id=gmail_id,
            format="full",
        )
        .execute()
    )


def build_gmail_sender_query(target_date: date | None = None) -> str:
    query = f"from:{TARGET_SENDER}"
    if target_date is None:
        return query
    next_day = target_date + timedelta(days=1)
    return (
        f"{query} "
        f"after:{target_date.strftime('%Y/%m/%d')} "
        f"before:{next_day.strftime('%Y/%m/%d')}"
    )


def collect_new_messages(
    service: Any,
    state: dict[str, Any],
    max_results: int,
    gmail_date: date | None = None,
) -> list[dict[str, Any]]:
    messages_by_id: dict[str, dict[str, Any]] = {}

    for gmail_id, record in state.get("messages", {}).items():
        if record.get("status") == "completed":
            continue
        try:
            messages_by_id[gmail_id] = fetch_gmail_message(service, gmail_id)
        except Exception as exc:
            record["resume_fetch_error"] = str(exc)

    queried_messages = iter_gmail_messages_with_query(
        service,
        query=build_gmail_sender_query(gmail_date),
        max_results=max_results,
    )
    message_state = state.get("messages", {})
    for message in queried_messages:
        gmail_id = str(message.get("id", ""))
        if message_state.get(gmail_id, {}).get("status") == "completed":
            continue
        messages_by_id[gmail_id] = message
    return sorted(messages_by_id.values(), key=message_sort_key)


def set_current(state: dict[str, Any], gmail_id: str | None, quote_key_value: str | None, stage: str) -> None:
    state["current"] = {
        "gmail_id": gmail_id,
        "quote_key": quote_key_value,
        "stage": stage,
        "updated_at": utc_now(),
    }


def update_completed_cursor(state: dict[str, Any], gmail_id: str, internal_date_ms: str | None) -> None:
    if not internal_date_ms:
        return
    cursor = state.setdefault("cursor", {})
    previous = cursor.get("last_completed_internal_date_ms")
    try:
        current_value = int(internal_date_ms)
        previous_value = int(previous) if previous else -1
    except ValueError:
        return
    if current_value >= previous_value:
        cursor["last_completed_internal_date_ms"] = internal_date_ms
        cursor["last_completed_gmail_id"] = gmail_id


def process_once(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, int]:
    service = get_gmail_service(args.credentials.expanduser(), args.token_cache.expanduser())
    verify_authorized_account(service)
    messages = collect_new_messages(service, state, args.max_results, args.gmail_date)
    provider_index = load_provider_catalog_index(args.providers_root)
    counters = {
        "messages_seen": len(messages),
        "messages_with_quotes": 0,
        "quotes_processed": 0,
        "quotes_skipped": 0,
        "quotes_postgres_persisted": 0,
        "quotes_postgres_updated": 0,
        "quotes_postgres_failed": 0,
        "quotes_postgres_skipped": 0,
        "quotes_agentic_reviewed": 0,
        "quotes_agentic_skipped": 0,
        "quotes_agentic_failed": 0,
    }

    for message in messages:
        message_record = extract_message(message)
        gmail_id = message_record.gmail_id or str(message.get("id", ""))
        set_current(state, gmail_id, None, "extracting_gmail_message")
        state.setdefault("messages", {})[gmail_id] = {
            "status": "in_progress",
            "message_id": message_record.message_id,
            "internal_date_ms": message_record.internal_date_ms,
            "received_at": message_record.received_at,
            "subject": message_record.subject,
            "extraction_status": message_record.extraction_status,
            "quote_keys": [],
            "warnings": message_record.warnings,
            "processed_at": utc_now(),
        }
        save_state(args.state_path, state)

        if message_record.extraction_status != "extracted":
            state["messages"][gmail_id]["status"] = "completed"
            state["messages"][gmail_id]["completed_at"] = utc_now()
            update_completed_cursor(state, gmail_id, message_record.internal_date_ms)
            set_current(state, None, None, "idle")
            save_state(args.state_path, state)
            continue

        counters["messages_with_quotes"] += 1
        for quote_url in message_record.quote_urls or ([message_record.quote_url] if message_record.quote_url else []):
            key = quote_key(message_record.message_id or gmail_id, quote_url)
            if key not in state["messages"][gmail_id]["quote_keys"]:
                state["messages"][gmail_id]["quote_keys"].append(key)
            existing = state.setdefault("quotes", {}).get(key)
            if existing and existing.get("status") == "processed" and not args.reprocess:
                counters["quotes_skipped"] += 1
                continue
            if not is_orbika_quote_url(quote_url):
                state.setdefault("quotes", {})[key] = {
                    "status": "invalid_quote_url",
                    "gmail_id": gmail_id,
                    "message_id": message_record.message_id,
                    "quote_url_masked": mask_url(quote_url),
                    "last_error": "Quote URL is not an Orbika external quote link.",
                    "last_error_at": utc_now(),
                }
                counters["quotes_skipped"] += 1
                save_state(args.state_path, state)
                continue

            state["quotes"][key] = {
                "status": "in_progress",
                "gmail_id": gmail_id,
                "message_id": message_record.message_id,
                "quote_url_masked": mask_url(quote_url),
                "started_at": utc_now(),
            }
            set_current(state, gmail_id, key, "fetching_orbika_quote")
            save_state(args.state_path, state)

            try:
                html, retries_used = fetch_quote_html(
                    quote_url=quote_url,
                    storage_state_path=args.storage_state.expanduser(),
                    headed=args.headed,
                    timeout_ms=args.timeout_ms,
                    max_retries=args.max_retries,
                    snapshot_dir=args.snapshot_dir / key if args.snapshot_dir else None,
                    allow_login_fallback=args.allow_login_fallback,
                )
            except Exception as exc:
                state["quotes"][key]["last_error"] = str(exc)
                state["quotes"][key]["last_error_at"] = utc_now()
                save_state(args.state_path, state)
                raise
            set_current(state, gmail_id, key, "parsing_orbika_quote")
            save_state(args.state_path, state)
            quote_record = parse_orbika_quote_html(html, quote_url, retries_used)
            if not quote_page_ready(html):
                quote_record.load_status = "failed_after_retries"
                if "Rendered quote page was still incomplete after retries." not in quote_record.warnings:
                    quote_record.warnings.append("Rendered quote page was still incomplete after retries.")

            supplier_matching = build_quote_match_report(
                quote_payload={
                    "quote_key": key,
                    "generated_at": utc_now(),
                    "source": {
                        "gmail_id": message_record.gmail_id,
                        "message_id": message_record.message_id,
                        "internal_date_ms": message_record.internal_date_ms,
                        "received_at": message_record.received_at,
                        "sender": message_record.sender,
                        "subject": message_record.subject,
                    },
                    "orbika": asdict(quote_record),
                },
                index=provider_index,
                limit_per_part=args.top_supplier_matches,
            )

            agentic_supplier_matching = None
            agentic_trace_path = None
            if args.skip_agentic_review:
                counters["quotes_agentic_skipped"] += 1
            else:
                set_current(state, gmail_id, key, "running_agentic_review")
                save_state(args.state_path, state)
                quote_payload = build_quote_output_payload(
                    key=key,
                    message_record=message_record,
                    quote_url=quote_url,
                    quote_record=quote_record,
                    supplier_matching=supplier_matching,
                )
                try:
                    agentic_supplier_matching, agentic_trace_path = add_agentic_review_to_quote_payload(
                        quote_payload,
                        trace_dir=args.agentic_trace_dir,
                        limit_per_part=args.agentic_limit_per_part,
                        model_name=args.agentic_model,
                    )
                    counters["quotes_agentic_reviewed"] += 1
                except Exception as exc:  # noqa: BLE001 - keep extraction and matching usable.
                    counters["quotes_agentic_failed"] += 1
                    state["quotes"][key]["agentic_review_error"] = str(exc)
                    state["quotes"][key]["agentic_review_error_at"] = utc_now()
                    print(f"warning: Agentic review failed for {key}: {exc}", file=sys.stderr)

            set_current(state, gmail_id, key, "writing_quote_output")
            save_state(args.state_path, state)
            output_path = write_quote_output(
                quotes_dir=args.quotes_dir,
                key=key,
                message_record=message_record,
                quote_url=quote_url,
                quote_record=quote_record,
                supplier_matching=supplier_matching,
                agentic_supplier_matching=agentic_supplier_matching,
            )
            set_current(state, gmail_id, key, "persisting_quote_to_postgres")
            save_state(args.state_path, state)
            postgres_persistence = persist_quote_output_to_postgres(output_path)
            if postgres_persistence["status"] == "persisted":
                if postgres_persistence.get("imported"):
                    counters["quotes_postgres_persisted"] += 1
                else:
                    counters["quotes_postgres_updated"] += 1
            elif postgres_persistence["status"] == "skipped":
                counters["quotes_postgres_skipped"] += 1
            else:
                counters["quotes_postgres_failed"] += 1
            state["quotes"][key] = {
                "status": "processed",
                "gmail_id": gmail_id,
                "message_id": message_record.message_id,
                "quote_url_masked": mask_url(quote_url),
                "output_path": str(output_path),
                "load_status": quote_record.load_status,
                "aviso_id": quote_record.aviso_id,
                "matching_parts_with_hits": supplier_matching["summary"]["parts_with_matches"],
                "matching_exact_reference_hits": supplier_matching["summary"]["exact_reference_matches"],
                "agentic_review_status": (agentic_supplier_matching or {}).get("review_mode")
                or ("skipped" if args.skip_agentic_review else "failed"),
                "agentic_trace_path": str(agentic_trace_path) if agentic_trace_path else None,
                "postgres_persistence": postgres_persistence,
                "processed_at": utc_now(),
            }
            counters["quotes_processed"] += 1
            save_state(args.state_path, state)

        state["messages"][gmail_id]["status"] = "completed"
        state["messages"][gmail_id]["completed_at"] = utc_now()
        update_completed_cursor(state, gmail_id, message_record.internal_date_ms)
        set_current(state, None, None, "idle")
        save_state(args.state_path, state)

    state["last_run"] = {
        "finished_at": utc_now(),
        **counters,
    }
    save_state(args.state_path, state)
    rebuild_daily_reports(args.quotes_dir, args.daily_report_dir)
    return counters


def format_poll_status(state: dict[str, Any], counters: dict[str, int], poll_seconds: int) -> str:
    current = state.get("current", {})
    stage = current.get("stage") or "idle"
    gmail_id = current.get("gmail_id")
    quote_key_value = current.get("quote_key")
    cursor = state.get("cursor", {})
    last_completed = cursor.get("last_completed_internal_date_ms") or "none"
    mode = state.get("last_run", {}).get("mode") or "incremental"
    return (
        "Incremental run finished: "
        f"{counters['messages_seen']} new message(s), "
        f"{counters['quotes_processed']} quote(s) processed, "
        f"{counters['quotes_skipped']} quote(s) skipped, "
        f"postgres persisted={counters.get('quotes_postgres_persisted', 0)} "
        f"updated={counters.get('quotes_postgres_updated', 0)} "
        f"failed={counters.get('quotes_postgres_failed', 0)} "
        f"skipped={counters.get('quotes_postgres_skipped', 0)}, "
        f"agentic reviewed={counters.get('quotes_agentic_reviewed', 0)} "
        f"failed={counters.get('quotes_agentic_failed', 0)} "
        f"skipped={counters.get('quotes_agentic_skipped', 0)}. "
        f"State: {state.get('last_run', {}).get('finished_at', 'unknown')} "
        f"mode={mode} "
        f"cursor={last_completed} "
        f"stage={stage} "
        f"gmail_id={gmail_id or 'none'} "
        f"quote_key={quote_key_value or 'none'} "
        f"sleeping={poll_seconds}s"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally process new Gmail Orbika quote emails in read-only mode."
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path(os.environ.get("GMAIL_OAUTH_CLIENT_SECRET", "")).expanduser()
        if os.environ.get("GMAIL_OAUTH_CLIENT_SECRET")
        else None,
        help="Gmail OAuth client secrets JSON path outside the repo.",
    )
    parser.add_argument("--token-cache", type=Path, default=DEFAULT_TOKEN_PATH)
    parser.add_argument("--storage-state", type=Path, default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--file-output-mode",
        choices=FILE_OUTPUT_MODES,
        default="minimal",
        help=(
            "Control local artifact generation. "
            "'minimal' keeps state, quotes and daily reports; "
            "'standard' also writes agentic traces; "
            "'debug' also writes HTML snapshots."
        ),
    )
    parser.add_argument("--quotes-dir", type=Path, default=None)
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--providers-root", type=Path, default=DEFAULT_PROVIDERS_ROOT)
    parser.add_argument("--daily-report-dir", type=Path, default=None)
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--poll-seconds", type=int, default=0)
    parser.add_argument("--top-supplier-matches", type=int, default=5)
    parser.add_argument("--agentic-limit-per-part", type=int, default=5)
    parser.add_argument("--agentic-model", type=str, default=None)
    parser.add_argument("--agentic-trace-dir", type=Path, default=None)
    parser.add_argument(
        "--skip-agentic-review",
        action="store_true",
        help="Skip automatic agentic supplier review and persist quote plus supplier matches only.",
    )
    parser.add_argument(
        "--gmail-date",
        type=date.fromisoformat,
        default=None,
        help="Restrict Gmail search to a single UTC calendar date in YYYY-MM-DD format.",
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--allow-login-fallback",
        action="store_true",
        help="Allow Orbika username/password login only as a fallback after quote URL reload recovery fails.",
    )
    parser.add_argument("--reprocess", action="store_true", help="Reprocess already completed quote keys.")
    args = parser.parse_args(argv)
    return resolve_output_dirs(args)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = Path.cwd()
    if args.credentials is None:
        raise SystemExit("Provide --credentials or GMAIL_OAUTH_CLIENT_SECRET.")
    reject_gmail_secret_path(args.credentials, repo_root, "OAuth client secrets")
    reject_gmail_secret_path(args.token_cache, repo_root, "OAuth token cache")
    reject_orbika_secret_path(args.storage_state, repo_root, "Playwright storage state")

    while True:
        state = load_state(args.state_path)
        counters = process_once(args, state)
        print(format_poll_status(state, counters, args.poll_seconds))
        if args.poll_seconds <= 0:
            return 0
        print(
            f"No new mail to process right now. Sleeping for {args.poll_seconds}s "
            f"before checking Gmail again."
        )
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
