#!/usr/bin/env python3
"""Import local Orbika quote JSON files into PostgreSQL.

This is a manual migration utility. It intentionally does not change the
incremental runner, backend API, frontend, or source JSON files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


DEFAULT_INPUT_DIR = Path("local/orbika_incremental/quotes")
VALID_QUOTE_STATUSES = {
    "new",
    "pending_extraction",
    "extracting",
    "extracted",
    "pending_matching",
    "matching",
    "pending_agentic_review",
    "agentic_reviewing",
    "ready_for_review",
    "needs_manual_review",
    "quoted",
    "sent",
    "failed",
    "needs_retry",
    "archived",
}
VALID_PART_STATUSES = {
    "requested",
    "matched",
    "no_match",
    "needs_review",
    "accepted",
    "discarded",
}


@dataclass
class Counters:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: int = 0
    emails: int = 0
    quotes: int = 0
    vehicles: int = 0
    workshops: int = 0
    parts: int = 0
    supplier_matches: int = 0
    agentic_reviews: int = 0
    warning_messages: list[str] = field(default_factory=list)

    def warn(self, source: Path, message: str) -> None:
        self.warnings += 1
        formatted = f"{source.name}: {message}"
        if len(self.warning_messages) < 50:
            self.warning_messages.append(formatted)


class DryRunRollback(Exception):
    """Internal signal used to rollback a successful dry-run transaction."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import local/orbika_incremental/quotes/*.json into PostgreSQL."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory with quote JSON files. Default: {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument("--limit", type=int, help="Import at most this many JSON files.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and run database statements inside a rolled-back transaction.",
    )
    return parser.parse_args()


def database_url_from_env() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL is required.")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def quote_files(input_dir: Path, limit: int | None) -> list[Path]:
    files = sorted(input_dir.glob("*.json"))
    if limit is not None:
        files = files[:limit]
    return files


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    return payload


def first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"no disponible", "none", "null"}:
            return text
    return None


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def sha256_text(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def derive_quote_status(payload: dict[str, Any]) -> str:
    orbika = payload.get("orbika") or {}
    if orbika.get("load_status") and orbika.get("load_status") != "loaded":
        return "needs_manual_review"
    if payload.get("agentic_supplier_matching"):
        return "ready_for_review"
    if payload.get("supplier_matching"):
        return "ready_for_review"
    if orbika:
        return "extracted"
    return "needs_manual_review"


def derive_part_status(
    raw_part: dict[str, Any],
    supplier_part: dict[str, Any] | None,
    agentic_part: dict[str, Any] | None,
) -> str:
    raw_status = first_text(raw_part.get("raw_status"))
    has_matches = bool((supplier_part or {}).get("matches")) or bool(
        (agentic_part or {}).get("selected_matches")
    )
    if has_matches:
        return "matched"
    if raw_status and "missing" in raw_status.lower():
        return "needs_review"
    if supplier_part is not None:
        return "no_match"
    return "requested"


def find_related_part(
    parts: list[dict[str, Any]], index: int, name: str | None
) -> dict[str, Any] | None:
    if index < len(parts):
        return parts[index]
    normalized = normalize_name(name)
    for part in parts:
        if normalize_name(first_text(part.get("part_name"))) == normalized:
            return part
    return None


def jsonb(value: Any) -> Jsonb:
    return Jsonb(value if value is not None else {})


def upsert_email(
    cur: psycopg.Cursor,
    payload: dict[str, Any],
    path: Path,
    quote_key: str,
    warnings: list[str],
) -> str:
    source = payload.get("source") or {}
    orbika = payload.get("orbika") or {}
    gmail_id = first_text(source.get("gmail_id"), source.get("message_id"), quote_key)
    sender = first_text(source.get("sender"), source.get("from"), orbika.get("email"))
    if not source.get("gmail_id"):
        warnings.append("source.gmail_id missing; using message_id or quote_key as email natural key")
    if not sender:
        sender = "unknown"
        warnings.append("source.sender missing; using 'unknown'")

    cur.execute(
        """
        INSERT INTO emails (
          gmail_id, message_id, thread_id, sender, subject, received_at,
          internal_date_ms, extraction_status, quote_url_count, warnings, raw_excerpt
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (gmail_id) DO UPDATE SET
          message_id = EXCLUDED.message_id,
          thread_id = EXCLUDED.thread_id,
          sender = EXCLUDED.sender,
          subject = EXCLUDED.subject,
          received_at = EXCLUDED.received_at,
          internal_date_ms = EXCLUDED.internal_date_ms,
          extraction_status = EXCLUDED.extraction_status,
          quote_url_count = EXCLUDED.quote_url_count,
          warnings = EXCLUDED.warnings,
          raw_excerpt = EXCLUDED.raw_excerpt
        RETURNING id
        """,
        (
            gmail_id,
            first_text(source.get("message_id")),
            first_text(source.get("thread_id")),
            sender,
            first_text(source.get("subject")),
            parse_datetime(source.get("received_at")),
            as_int(source.get("internal_date_ms")),
            "extracted" if payload.get("orbika") else "needs_manual_review",
            1 if payload.get("quote_url_masked") else 0,
            jsonb(warnings),
            first_text(source.get("raw_excerpt")),
        ),
    )
    return cur.fetchone()["id"]


def upsert_quote(
    cur: psycopg.Cursor,
    payload: dict[str, Any],
    path: Path,
    quote_key: str,
    email_id: str,
    warnings: list[str],
) -> tuple[str, bool]:
    source = payload.get("source") or {}
    orbika = payload.get("orbika") or {}
    status = derive_quote_status(payload)
    if status not in VALID_QUOTE_STATUSES:
        status = "needs_manual_review"

    cur.execute("SELECT id FROM quotes WHERE quote_key = %s", (quote_key,))
    existing = cur.fetchone()
    existed = existing is not None

    cur.execute(
        """
        INSERT INTO quotes (
          quote_key, email_id, aviso_id, insurer, source_subject, quote_url_masked,
          quote_url_hash, load_status, status, priority, received_at, processed_at,
          ready_for_review_at, last_error, warnings, source_file_path
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (quote_key) DO UPDATE SET
          email_id = EXCLUDED.email_id,
          aviso_id = EXCLUDED.aviso_id,
          insurer = EXCLUDED.insurer,
          source_subject = EXCLUDED.source_subject,
          quote_url_masked = EXCLUDED.quote_url_masked,
          quote_url_hash = EXCLUDED.quote_url_hash,
          load_status = EXCLUDED.load_status,
          status = EXCLUDED.status,
          priority = EXCLUDED.priority,
          received_at = EXCLUDED.received_at,
          processed_at = EXCLUDED.processed_at,
          ready_for_review_at = EXCLUDED.ready_for_review_at,
          last_error = EXCLUDED.last_error,
          warnings = EXCLUDED.warnings,
          source_file_path = EXCLUDED.source_file_path
        RETURNING id
        """,
        (
            quote_key,
            email_id,
            first_text(orbika.get("aviso_id")),
            insurer_from_subject(source.get("subject")),
            first_text(source.get("subject")),
            first_text(payload.get("quote_url_masked")),
            sha256_text(first_text(payload.get("quote_url_masked"))),
            first_text(orbika.get("load_status")),
            status,
            "normal",
            parse_datetime(source.get("received_at")),
            parse_datetime(payload.get("generated_at")),
            parse_datetime(
                (payload.get("agentic_supplier_matching") or {}).get("generated_at")
                or (payload.get("supplier_matching") or {}).get("generated_at")
            ),
            first_text(orbika.get("error")),
            jsonb(warnings),
            str(path),
        ),
    )
    return cur.fetchone()["id"], existed


def insurer_from_subject(subject: Any) -> str | None:
    text = first_text(subject)
    if not text or "_" not in text:
        return None
    candidate = text.rsplit("_", 1)[-1].strip()
    return candidate or None


def upsert_vehicle(cur: psycopg.Cursor, quote_id: str, orbika: dict[str, Any]) -> bool:
    has_vehicle = any(
        first_text(orbika.get(key))
        for key in ("placa", "marca", "linea", "version", "ano", "vin")
    )
    if not has_vehicle:
        return False
    cur.execute(
        """
        INSERT INTO vehicles (
          quote_id, plate, brand, line, version, model_year, vin, color, raw_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (quote_id) DO UPDATE SET
          plate = EXCLUDED.plate,
          brand = EXCLUDED.brand,
          line = EXCLUDED.line,
          version = EXCLUDED.version,
          model_year = EXCLUDED.model_year,
          vin = EXCLUDED.vin,
          color = EXCLUDED.color,
          raw_payload = EXCLUDED.raw_payload
        """,
        (
            quote_id,
            first_text(orbika.get("placa")),
            first_text(orbika.get("marca")),
            first_text(orbika.get("linea")),
            first_text(orbika.get("version")),
            as_int(orbika.get("ano")),
            first_text(orbika.get("vin")),
            first_text(orbika.get("color")),
            jsonb({key: orbika.get(key) for key in ("placa", "marca", "linea", "version", "ano", "vin", "color")}),
        ),
    )
    return True


def upsert_workshop(cur: psycopg.Cursor, quote_id: str, orbika: dict[str, Any]) -> bool:
    has_workshop = any(
        first_text(orbika.get(key))
        for key in ("nombre_comercial", "taller_entrega", "ciudad", "direccion", "telefono")
    )
    if not has_workshop:
        return False
    cur.execute(
        """
        INSERT INTO workshops (
          quote_id, commercial_name, delivery_workshop, city, address, phone, raw_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (quote_id) DO UPDATE SET
          commercial_name = EXCLUDED.commercial_name,
          delivery_workshop = EXCLUDED.delivery_workshop,
          city = EXCLUDED.city,
          address = EXCLUDED.address,
          phone = EXCLUDED.phone,
          raw_payload = EXCLUDED.raw_payload
        """,
        (
            quote_id,
            first_text(orbika.get("nombre_comercial")),
            first_text(orbika.get("taller_entrega")),
            first_text(orbika.get("ciudad")),
            first_text(orbika.get("direccion")),
            first_text(orbika.get("telefono")),
            jsonb(
                {
                    key: orbika.get(key)
                    for key in (
                        "nombre_comercial",
                        "taller_entrega",
                        "nit",
                        "ciudad",
                        "direccion",
                        "telefono",
                        "email",
                    )
                }
            ),
        ),
    )
    return True


def replace_parts_and_children(
    cur: psycopg.Cursor,
    payload: dict[str, Any],
    path: Path,
    quote_id: str,
    quote_key: str,
    counters: Counters,
    warnings: list[str],
) -> None:
    orbika = payload.get("orbika") or {}
    raw_parts = orbika.get("parts") or []
    if not isinstance(raw_parts, list):
        warnings.append("orbika.parts is not a list; skipping parts")
        raw_parts = []

    supplier_parts = (payload.get("supplier_matching") or {}).get("parts") or []
    agentic_parts = (payload.get("agentic_supplier_matching") or {}).get("parts") or []
    provider_specs = {
        spec.get("provider_id"): spec
        for spec in (payload.get("supplier_matching") or {}).get("provider_specs") or []
        if isinstance(spec, dict)
    }

    cur.execute("DELETE FROM parts WHERE quote_id = %s", (quote_id,))

    trace_path = Path("local/orbika_incremental/agentic_traces") / f"{quote_key}.agentic_trace.json"

    for index, raw_part in enumerate(raw_parts, start=1):
        if not isinstance(raw_part, dict):
            warnings.append(f"part #{index} is not an object; skipping")
            counters.warn(path, f"part #{index} is not an object; skipped")
            continue
        name = first_text(raw_part.get("name"), raw_part.get("part_name"))
        if not name:
            name = f"Unnamed part {index}"
            warnings.append(f"part #{index} missing name; using generated name")

        supplier_part = find_related_part(supplier_parts, index - 1, name)
        agentic_part = find_related_part(agentic_parts, index - 1, name)
        status = derive_part_status(raw_part, supplier_part, agentic_part)
        if status not in VALID_PART_STATUSES:
            status = "requested"

        cur.execute(
            """
            INSERT INTO parts (
              quote_id, position, name, normalized_name, requested_reference,
              quantity, raw_status, status, observations, raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                quote_id,
                index,
                name,
                normalize_name(name),
                first_text(raw_part.get("reference"), (supplier_part or {}).get("requested_reference")),
                as_decimal(raw_part.get("quantity")),
                first_text(raw_part.get("raw_status")),
                status,
                first_text(raw_part.get("reference_validation_text"), raw_part.get("quality")),
                jsonb(raw_part),
            ),
        )
        part_id = cur.fetchone()["id"]
        counters.parts += 1

        match_ids = insert_supplier_matches(
            cur, part_id, supplier_part, provider_specs, path, counters, warnings
        )
        insert_agentic_review(
            cur,
            part_id,
            agentic_part,
            match_ids,
            path,
            trace_path if trace_path.exists() else None,
            payload,
            counters,
            warnings,
        )


def insert_supplier_matches(
    cur: psycopg.Cursor,
    part_id: str,
    supplier_part: dict[str, Any] | None,
    provider_specs: dict[str, dict[str, Any]],
    path: Path,
    counters: Counters,
    warnings: list[str],
) -> dict[tuple[Any, ...], str]:
    match_ids: dict[tuple[Any, ...], str] = {}
    if not supplier_part:
        return match_ids
    matches = supplier_part.get("matches") or []
    if not isinstance(matches, list):
        warnings.append("supplier matches is not a list; skipping matches for one part")
        counters.warn(path, "supplier matches is not a list; skipped")
        return match_ids

    for rank, match in enumerate(matches, start=1):
        if not isinstance(match, dict):
            warnings.append(f"supplier match rank {rank} is not an object; skipping")
            continue
        provider_id = first_text(match.get("provider_id"))
        product_name = first_text(match.get("product_name"))
        if not provider_id:
            provider_id = "unknown"
            warnings.append(f"supplier match rank {rank} missing provider_id; using 'unknown'")
        if not product_name:
            product_name = "Unknown product"
            warnings.append(f"supplier match rank {rank} missing product_name; using fallback")
        score = as_int(match.get("score_percent"))
        if score is None:
            score = 0
            warnings.append(f"supplier match rank {rank} missing score_percent; using 0")
        score = max(0, min(score, 100))
        provider_spec = provider_specs.get(provider_id) or {}

        cur.execute(
            """
            INSERT INTO supplier_matches (
              part_id, provider_id, provider_name, product_name, reference, sku,
              brand, category_name, subcategory_name, detail_url, detail_url_hash,
              price, currency, availability, match_type, score_percent, rank,
              reasons, risk_flags, snapshot_ref, raw_payload
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (
                part_id,
                provider_id,
                first_text(match.get("provider_name"), provider_spec.get("display_name")),
                product_name,
                first_text(match.get("reference")),
                first_text(match.get("sku")),
                first_text(match.get("brand")),
                first_text(match.get("category_name")),
                first_text(match.get("subcategory_name")),
                first_text(match.get("detail_url")),
                sha256_text(first_text(match.get("detail_url"))),
                as_decimal(match.get("price")),
                first_text(match.get("currency")) or "COP",
                first_text(match.get("availability")),
                first_text(match.get("match_type")),
                score,
                as_int(match.get("rank")) or rank,
                jsonb(match.get("reasons") or []),
                jsonb(match.get("risk_flags") or []),
                first_text(match.get("snapshot_ref"), provider_spec.get("snapshot_date")),
                jsonb(match),
            ),
        )
        match_id = cur.fetchone()["id"]
        counters.supplier_matches += 1
        match_ids[match_key(match, rank)] = match_id
    return match_ids


def match_key(match: dict[str, Any], fallback_rank: int | None = None) -> tuple[Any, ...]:
    return (
        as_int(match.get("rank")) or fallback_rank,
        first_text(match.get("provider_id")),
        first_text(match.get("product_name")),
        first_text(match.get("reference")),
        first_text(match.get("detail_url")),
    )


def insert_agentic_review(
    cur: psycopg.Cursor,
    part_id: str,
    agentic_part: dict[str, Any] | None,
    match_ids: dict[tuple[Any, ...], str],
    path: Path,
    trace_path: Path | None,
    payload: dict[str, Any],
    counters: Counters,
    warnings: list[str],
) -> None:
    if not agentic_part:
        return
    selected = agentic_part.get("selected_matches") or []
    if not isinstance(selected, list):
        warnings.append("agentic selected_matches is not a list; skipping review for one part")
        counters.warn(path, "agentic selected_matches is not a list; skipped")
        return
    agentic_root = payload.get("agentic_supplier_matching") or {}
    top_match_id = None
    if selected:
        first = selected[0] if isinstance(selected[0], dict) else {}
        top_match_id = match_ids.get(match_key(first, 1))
        if top_match_id is None:
            for key, value in match_ids.items():
                if key[1] == first_text(first.get("provider_id")) and key[2] == first_text(first.get("product_name")):
                    top_match_id = value
                    break

    confidence = as_int(agentic_part.get("top_score_percent"))
    if confidence is not None:
        confidence = max(0, min(confidence, 100))
    summary_comment = None
    for option in selected:
        if isinstance(option, dict):
            summary_comment = first_text(option.get("agentic_comment"))
            if summary_comment:
                break

    cur.execute(
        """
        INSERT INTO agentic_reviews (
          part_id, top_match_id, reviewer_mode, model, status, confidence_percent,
          summary_comment, selected_options, risk_notes, preference_notes,
          trace_file_path
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            part_id,
            top_match_id,
            first_text(agentic_root.get("review_mode")) or "unknown",
            first_text(agentic_root.get("model")),
            "reviewed" if selected else "no_selection",
            confidence,
            summary_comment,
            jsonb(selected),
            jsonb(agentic_part.get("risk_notes") or []),
            jsonb(agentic_part.get("preference_notes") or []),
            str(trace_path) if trace_path else None,
        ),
    )
    counters.agentic_reviews += 1


def import_one(cur: psycopg.Cursor, path: Path, counters: Counters) -> None:
    payload = read_json(path)
    quote_key = first_text(payload.get("quote_key"), path.stem)
    if not quote_key:
        counters.skipped += 1
        counters.warn(path, "missing quote_key; skipped")
        return

    warnings: list[str] = []
    orbika_warnings = (payload.get("orbika") or {}).get("warnings") or []
    if isinstance(orbika_warnings, list):
        warnings.extend(str(item) for item in orbika_warnings)
    else:
        warnings.append("orbika.warnings is not a list")

    email_id = upsert_email(cur, payload, path, quote_key, warnings)
    counters.emails += 1
    quote_id, existed = upsert_quote(cur, payload, path, quote_key, email_id, warnings)
    counters.quotes += 1
    if existed:
        counters.updated += 1
    else:
        counters.imported += 1

    orbika = payload.get("orbika") or {}
    if not orbika:
        warnings.append("orbika object missing")
        counters.warn(path, "orbika object missing")
    if upsert_vehicle(cur, quote_id, orbika):
        counters.vehicles += 1
    else:
        warnings.append("vehicle fields missing")
        counters.warn(path, "vehicle fields missing")
    if upsert_workshop(cur, quote_id, orbika):
        counters.workshops += 1
    else:
        warnings.append("workshop fields missing")
        counters.warn(path, "workshop fields missing")

    replace_parts_and_children(cur, payload, path, quote_id, quote_key, counters, warnings)

    if warnings:
        cur.execute(
            "UPDATE emails SET warnings = %s WHERE id = %s",
            (jsonb(warnings), email_id),
        )
        cur.execute(
            "UPDATE quotes SET warnings = %s WHERE id = %s",
            (jsonb(warnings), quote_id),
        )
        for warning in warnings:
            counters.warn(path, warning)


def print_summary(counters: Counters, dry_run: bool) -> None:
    mode = "dry-run" if dry_run else "import"
    print(f"mode={mode}")
    print(
        "quotes: "
        f"imported={counters.imported} updated={counters.updated} "
        f"skipped={counters.skipped} failed={counters.failed}"
    )
    print(
        "rows touched: "
        f"emails={counters.emails} quotes={counters.quotes} vehicles={counters.vehicles} "
        f"workshops={counters.workshops} parts={counters.parts} "
        f"supplier_matches={counters.supplier_matches} "
        f"agentic_reviews={counters.agentic_reviews}"
    )
    print(f"warnings={counters.warnings}")
    for warning in counters.warning_messages:
        print(f"warning: {warning}")
    if counters.warnings > len(counters.warning_messages):
        remaining = counters.warnings - len(counters.warning_messages)
        print(f"warning: {remaining} additional warnings not shown")


def main() -> int:
    args = parse_args()
    files = quote_files(args.input_dir, args.limit)
    counters = Counters()
    if not files:
        print(f"No quote JSON files found in {args.input_dir}", file=sys.stderr)
        return 1

    url = database_url_from_env()
    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    for path in files:
                        try:
                            import_one(cur, path, counters)
                        except Exception as exc:  # noqa: BLE001 - keep batch import moving.
                            counters.failed += 1
                            counters.warn(path, f"failed: {exc}")
                    if args.dry_run:
                        raise DryRunRollback()
        except DryRunRollback:
            pass

    print_summary(counters, args.dry_run)
    return 1 if counters.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
