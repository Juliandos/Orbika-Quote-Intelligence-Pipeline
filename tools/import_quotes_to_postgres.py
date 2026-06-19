#!/usr/bin/env python3
"""Import local Orbika quote JSON files into PostgreSQL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.postgres_quote_persistence import (
    Counters,
    database_url_from_env,
    persist_quote_files,
    quote_files,
)


DEFAULT_INPUT_DIR = Path("local/orbika_incremental/quotes")


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
    if not files:
        print(f"No quote JSON files found in {args.input_dir}", file=sys.stderr)
        return 1

    database_url = database_url_from_env()
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    counters = persist_quote_files(files, database_url=database_url, dry_run=args.dry_run)
    print_summary(counters, args.dry_run)
    return 1 if counters.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
