#!/usr/bin/env python3
"""Ingest the latest provider catalog snapshots into PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tools.postgres_quote_persistence import database_url_from_env, normalize_name
from tools.supplier_quote_matcher import DEFAULT_PROVIDERS_ROOT, load_provider_catalog_index_from_snapshots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers-root",
        type=Path,
        default=DEFAULT_PROVIDERS_ROOT,
        help=f"Provider catalog root. Default: {DEFAULT_PROVIDERS_ROOT}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and run database statements inside a rolled-back transaction.",
    )
    return parser.parse_args()


def jsonb(value: Any) -> Jsonb:
    return Jsonb(value if value is not None else {})


def file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_snapshot_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def normalize_tokens(tokens: set[str] | frozenset[str]) -> list[str]:
    return sorted(token for token in tokens if token)


def ingest_provider_catalog_index(
    *,
    providers_root: Path,
    database_url: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    index = load_provider_catalog_index_from_snapshots(providers_root)
    provider_buckets: dict[str, list[int]] = defaultdict(list)
    for item_index, item in enumerate(index.items):
        provider_buckets[item.provider_id].append(item_index)

    counters = {
        "providers_seen": 0,
        "snapshots_upserted": 0,
        "products_upserted": 0,
        "failed": 0,
    }

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    for provider_id, item_indexes in sorted(provider_buckets.items()):
                        provider_spec = index.provider_specs.get(provider_id) or {}
                        if not item_indexes:
                            continue
                        first_item = index.items[item_indexes[0]]
                        snapshot_path = Path(provider_spec.get("snapshot_path") or "")
                        source_hash = file_sha256(snapshot_path)
                        snapshot_date = parse_snapshot_date(provider_spec.get("snapshot_date"))
                        provider_metadata = {
                            "provider_id": provider_id,
                            "display_name": provider_spec.get("display_name"),
                            "website": provider_spec.get("website"),
                            "matching": provider_spec.get("matching") or {},
                            "data_precision": provider_spec.get("data_precision") or {},
                            "notes": provider_spec.get("notes") or [],
                        }
                        snapshot_metadata = {
                            "snapshot_path": str(snapshot_path) if snapshot_path else None,
                            "snapshot_date": provider_spec.get("snapshot_date"),
                        }
                        cur.execute(
                            """
                            INSERT INTO provider_catalog_snapshots (
                              provider_id, provider_name, provider_type, snapshot_date,
                              source_path, source_hash, product_count, provider_metadata,
                              snapshot_metadata, notes, status, loaded_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                            ON CONFLICT (source_path) DO UPDATE SET
                              provider_name = EXCLUDED.provider_name,
                              provider_type = EXCLUDED.provider_type,
                              snapshot_date = EXCLUDED.snapshot_date,
                              source_hash = EXCLUDED.source_hash,
                              product_count = EXCLUDED.product_count,
                              provider_metadata = EXCLUDED.provider_metadata,
                              snapshot_metadata = EXCLUDED.snapshot_metadata,
                              notes = EXCLUDED.notes,
                              status = EXCLUDED.status,
                              loaded_at = now()
                            RETURNING id
                            """,
                            (
                                provider_id,
                                provider_spec.get("display_name") or first_item.provider_name,
                                first_item.provider_type,
                                snapshot_date,
                                str(snapshot_path) if snapshot_path else None,
                                source_hash,
                                len(item_indexes),
                                jsonb(provider_metadata),
                                jsonb(snapshot_metadata),
                                jsonb(provider_spec.get("notes") or []),
                                "loaded",
                            ),
                        )
                        snapshot_id = cur.fetchone()["id"]
                        counters["snapshots_upserted"] += 1
                        cur.execute(
                            "DELETE FROM provider_products WHERE snapshot_id = %s",
                            (snapshot_id,),
                        )
                        for item_index in item_indexes:
                            item = index.items[item_index]
                            searchable_tokens = normalize_tokens(item.searchable_tokens)
                            taxonomy_labels = sorted(item.taxonomy_labels)
                            searchable_text = " ".join(
                                value
                                for value in (
                                    item.title,
                                    item.category_name,
                                    item.subcategory_name,
                                    item.brand,
                                    item.reference,
                                    item.sku,
                                    item.supplier_item_code,
                                )
                                if value
                            )
                            raw_payload = {
                                "provider_id": item.provider_id,
                                "provider_name": item.provider_name,
                                "provider_type": item.provider_type,
                                "detail_url": item.detail_url,
                                "title": item.title,
                                "category_name": item.category_name,
                                "subcategory_name": item.subcategory_name,
                                "brand": item.brand,
                                "reference": item.reference,
                                "sku": item.sku,
                                "supplier_item_code": item.supplier_item_code,
                                "taxonomy_labels": taxonomy_labels,
                                "searchable_tokens": searchable_tokens,
                                "raw_match_type": item.raw_match_type,
                                "requires_manual_confirmation": item.requires_manual_confirmation,
                                "notes": list(item.notes),
                            }
                            cur.execute(
                                """
                                INSERT INTO provider_products (
                                  snapshot_id, provider_id, provider_name, provider_type,
                                  title, normalized_title, category_name, subcategory_name,
                                  brand, reference, sku, supplier_item_code, detail_url,
                                  detail_url_hash, raw_match_type, requires_manual_confirmation,
                                  searchable_text, searchable_tokens, taxonomy_labels, notes,
                                  raw_payload
                                )
                                VALUES (
                                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                                )
                                """,
                                (
                                    snapshot_id,
                                    item.provider_id,
                                    item.provider_name,
                                    item.provider_type,
                                    item.title,
                                    normalize_name(item.title),
                                    item.category_name,
                                    item.subcategory_name,
                                    item.brand,
                                    item.reference,
                                    item.sku,
                                    item.supplier_item_code,
                                    item.detail_url,
                                    hashlib.sha256(item.detail_url.encode("utf-8")).hexdigest()
                                    if item.detail_url
                                    else None,
                                    item.raw_match_type,
                                    item.requires_manual_confirmation,
                                    searchable_text,
                                    jsonb(searchable_tokens),
                                    jsonb(taxonomy_labels),
                                    jsonb(list(item.notes)),
                                    jsonb(raw_payload),
                                ),
                            )
                            counters["products_upserted"] += 1
                        counters["providers_seen"] += 1
                if dry_run:
                    raise RuntimeError("dry-run rollback")
        except RuntimeError as exc:
            if str(exc) != "dry-run rollback":
                raise
    return counters


def main() -> int:
    args = parse_args()
    database_url = database_url_from_env()
    if not database_url:
        print("DATABASE_URL is required for provider catalog ingestion.", file=sys.stderr)
        return 1
    if not args.providers_root.exists():
        print(f"Providers root not found: {args.providers_root}", file=sys.stderr)
        return 1

    counters = ingest_provider_catalog_index(
        providers_root=args.providers_root,
        database_url=database_url,
        dry_run=args.dry_run,
    )
    print(
        "provider catalog ingest: "
        f"providers_seen={counters['providers_seen']} "
        f"snapshots_upserted={counters['snapshots_upserted']} "
        f"products_upserted={counters['products_upserted']} "
        f"failed={counters['failed']}"
    )
    return 1 if counters["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

