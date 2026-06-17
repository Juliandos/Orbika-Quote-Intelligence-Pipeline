from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import QUOTES_DIR, STATE_PATH


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def quote_paths(quotes_dir: Path = QUOTES_DIR) -> list[Path]:
    if not quotes_dir.exists():
        return []
    return sorted(quotes_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def list_quotes(quotes_dir: Path = QUOTES_DIR) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in quote_paths(quotes_dir):
        payload = load_json(path)
        orbika = payload.get("orbika", {})
        matching = payload.get("supplier_matching", {})
        agentic = payload.get("agentic_supplier_matching", {})
        items.append(
            {
                "quote_key": payload.get("quote_key"),
                "path": str(path),
                "generated_at": payload.get("generated_at"),
                "received_at": payload.get("source", {}).get("received_at"),
                "subject": payload.get("source", {}).get("subject"),
                "aviso_id": orbika.get("aviso_id"),
                "placa": orbika.get("placa"),
                "marca": orbika.get("marca"),
                "linea": orbika.get("linea"),
                "load_status": orbika.get("load_status"),
                "repuestos_count": orbika.get("repuestos_count", 0),
                "parts_with_matches": matching.get("summary", {}).get("parts_with_matches", 0),
                "exact_reference_matches": matching.get("summary", {}).get("exact_reference_matches", 0),
                "parts_with_agentic_matches": agentic.get("summary", {}).get(
                    "parts_with_agentic_matches", 0
                ),
            }
        )
    return items


def get_quote_detail(quote_key: str, quotes_dir: Path = QUOTES_DIR) -> dict[str, Any] | None:
    path = quotes_dir / f"{quote_key}.json"
    if not path.exists():
        return None
    return load_json(path)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    return load_json(STATE_PATH)


def build_dashboard(quotes_dir: Path = QUOTES_DIR) -> dict[str, Any]:
    quotes = list_quotes(quotes_dir)
    provider_hits: Counter[str] = Counter()
    load_status: Counter[str] = Counter()
    for item in quotes:
        load_status[str(item.get("load_status") or "unknown")] += 1
        detail = get_quote_detail(str(item["quote_key"]), quotes_dir=quotes_dir)
        for provider_id, count in (
            detail.get("supplier_matching", {}).get("summary", {}).get("provider_hits", {}) if detail else {}
        ).items():
            provider_hits[provider_id] += int(count)

    state = load_state()
    last_run = state.get("last_run", {})
    current = state.get("current", {})
    latest_quote_at = quotes[0]["generated_at"] if quotes else None
    return {
        "counts": {
            "quotes_total": len(quotes),
            "loaded_quotes": load_status.get("loaded", 0),
            "failed_quotes": load_status.get("failed_after_retries", 0),
            "partial_quotes": load_status.get("partial", 0),
        },
        "last_run": last_run,
        "current": current,
        "latest_quote_at": latest_quote_at,
        "provider_hits": dict(provider_hits.most_common()),
        "recent_quotes": quotes[:8],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
