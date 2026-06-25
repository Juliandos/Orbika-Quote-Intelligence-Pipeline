#!/usr/bin/env python3
"""Load lightweight customer/workshop preferences for quote ranking."""

from __future__ import annotations

import os
import unicodedata
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row

    PSYCOPG_AVAILABLE = True
except Exception:  # pragma: no cover - optional when DB access is unavailable.
    psycopg = None
    dict_row = None
    PSYCOPG_AVAILABLE = False


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def _database_url() -> str | None:
    value = os.environ.get("DATABASE_URL")
    if not value:
        return None
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = _normalize_text(value)
    if text in {"1", "true", "yes", "si", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _insurer_from_subject(subject: Any) -> str | None:
    text = _first_text(subject)
    if not text or "_" not in text:
        return None
    return _normalize_text(text.rsplit("_", 1)[-1])


def _scope_candidates(quote_payload: dict[str, Any]) -> list[tuple[str, str | None]]:
    source = quote_payload.get("source") or {}
    orbika = quote_payload.get("orbika") or {}
    candidates: list[tuple[str, str | None]] = [("global", None)]

    insurer = _insurer_from_subject(source.get("subject"))
    if insurer:
        candidates.append(("insurer", insurer))

    for workshop_value in (
        orbika.get("nombre_comercial"),
        orbika.get("taller_entrega"),
    ):
        normalized = _normalize_text(workshop_value)
        if normalized and ("workshop", normalized) not in candidates:
            candidates.append(("workshop", normalized))

    brand = _normalize_text(orbika.get("marca"))
    if brand:
        candidates.append(("vehicle_brand", brand))

    return candidates


def _empty_bundle() -> dict[str, Any]:
    return {
        "preferred_providers": [],
        "avoided_providers": [],
        "preferred_brands": [],
        "avoided_brands": [],
        "prefer_exact_reference": False,
        "year_tolerance": 0,
        "max_options_per_part": None,
        "notes": [],
        "applied_scopes": [],
        "applied_preferences": [],
    }


def _iter_values(value: Any, *keys: str) -> list[str]:
    if isinstance(value, list):
        return [item for item in (_normalize_text(entry) for entry in value) if item]
    if isinstance(value, dict):
        results: list[str] = []
        for key in keys:
            current = value.get(key)
            if isinstance(current, list):
                results.extend(
                    item for item in (_normalize_text(entry) for entry in current) if item
                )
            else:
                normalized = _normalize_text(current)
                if normalized:
                    results.append(normalized)
        return results
    normalized = _normalize_text(value)
    return [normalized] if normalized else []


def _apply_record(bundle: dict[str, Any], record: dict[str, Any]) -> None:
    preference_type = _normalize_text(record.get("preference_type"))
    raw_value = record.get("value")
    note = _first_text(record.get("notes"))
    scope = _normalize_text(record.get("scope"))
    scope_key = _normalize_text(record.get("scope_key"))

    if scope and (scope, scope_key or None) not in bundle["applied_scopes"]:
        bundle["applied_scopes"].append((scope, scope_key or None))

    if preference_type in {"preferred_provider", "provider_preference"}:
        bundle["preferred_providers"].extend(
            _iter_values(raw_value, "provider_id", "provider_ids", "providers")
        )
    elif preference_type in {"avoided_provider", "provider_avoid"}:
        bundle["avoided_providers"].extend(
            _iter_values(raw_value, "provider_id", "provider_ids", "providers")
        )
    elif preference_type in {"preferred_brand", "brand_preference"}:
        bundle["preferred_brands"].extend(
            _iter_values(raw_value, "brand", "brands")
        )
    elif preference_type in {"avoided_brand", "brand_avoid"}:
        bundle["avoided_brands"].extend(
            _iter_values(raw_value, "brand", "brands")
        )
    elif preference_type == "prefer_exact_reference":
        value = _as_bool(raw_value.get("enabled") if isinstance(raw_value, dict) else raw_value)
        if value is not None:
            bundle["prefer_exact_reference"] = value
    elif preference_type == "year_tolerance":
        raw_number = raw_value.get("years") if isinstance(raw_value, dict) else raw_value
        value = _as_int(raw_number)
        if value is not None:
            bundle["year_tolerance"] = max(0, value)
    elif preference_type == "max_options_per_part":
        raw_number = raw_value.get("count") if isinstance(raw_value, dict) else raw_value
        value = _as_int(raw_number)
        if value is not None:
            bundle["max_options_per_part"] = max(1, min(value, 5))

    if note:
        bundle["notes"].append(note)
    if preference_type:
        bundle["applied_preferences"].append(preference_type)


def _dedupe_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "preferred_providers",
        "avoided_providers",
        "preferred_brands",
        "avoided_brands",
        "notes",
        "applied_preferences",
    ):
        bundle[key] = list(dict.fromkeys(bundle[key]))
    bundle["applied_scopes"] = [
        {"scope": scope, "scope_key": scope_key}
        for scope, scope_key in bundle["applied_scopes"]
    ]
    return bundle


def _preference_records_from_db(quote_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not PSYCOPG_AVAILABLE:
        return []
    database_url = _database_url()
    if not database_url:
        return []

    records: list[dict[str, Any]] = []
    scope_candidates = _scope_candidates(quote_payload)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for scope, scope_key in scope_candidates:
                if scope_key is None:
                    cur.execute(
                        """
                        SELECT scope, scope_key, preference_type, value, notes
                        FROM customer_preferences
                        WHERE active = true
                          AND scope = %s
                          AND scope_key IS NULL
                        ORDER BY created_at ASC
                        """,
                        (scope,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT scope, scope_key, preference_type, value, notes
                        FROM customer_preferences
                        WHERE active = true
                          AND scope = %s
                          AND scope_key = %s
                        ORDER BY created_at ASC
                        """,
                        (scope, scope_key),
                    )
                records.extend(cur.fetchall())
    return records


def load_customer_preferences_for_quote(quote_payload: dict[str, Any]) -> dict[str, Any]:
    bundle = _empty_bundle()
    raw_records = quote_payload.get("customer_preferences")
    records: list[dict[str, Any]]

    if isinstance(raw_records, list) and raw_records:
        records = [record for record in raw_records if isinstance(record, dict)]
    else:
        try:
            records = _preference_records_from_db(quote_payload)
        except Exception:
            records = []

    for record in records:
        _apply_record(bundle, record)

    return _dedupe_bundle(bundle)
