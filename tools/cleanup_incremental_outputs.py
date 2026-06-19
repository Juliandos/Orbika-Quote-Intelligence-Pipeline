#!/usr/bin/env python3
"""Dry-run cleanup helper for local Orbika incremental artifacts."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


DEFAULT_ROOT = Path("local/orbika_incremental")
EXPERIMENT_PREFIXES = ("backfill-", "check-", "phase", "retest-")
DEBUG_DIRECTORIES = ("agentic_traces", "snapshots", "debug")


@dataclass
class CleanupCandidate:
    path: Path
    reason: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_older_than(path: Path, *, cutoff: datetime) -> bool:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return modified < cutoff


def iter_debug_candidates(root: Path, *, cutoff: datetime) -> list[CleanupCandidate]:
    candidates: list[CleanupCandidate] = []
    for name in DEBUG_DIRECTORIES:
        target = root / name
        if not target.exists():
            continue
        for child in sorted(target.iterdir()):
            if is_older_than(child, cutoff=cutoff):
                candidates.append(CleanupCandidate(child, f"{name} older than retention"))
    return candidates


def iter_experiment_candidates(root: Path, *, cutoff: datetime) -> list[CleanupCandidate]:
    candidates: list[CleanupCandidate] = []
    for child in sorted(root.iterdir()):
        if child.name in DEBUG_DIRECTORIES or child.name in {"quotes", "daily", "state.json"}:
            continue
        if child.name.startswith(EXPERIMENT_PREFIXES) and is_older_than(child, cutoff=cutoff):
            candidates.append(CleanupCandidate(child, "experimental artifact older than retention"))
    return candidates


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or remove stale local Orbika incremental artifacts. "
            "Dry-run is the default."
        )
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--debug-retention-days",
        type=int,
        default=7,
        help="Retention for agentic_traces, snapshots and debug artifacts.",
    )
    parser.add_argument(
        "--experiment-retention-days",
        type=int,
        default=7,
        help="Retention for check/backfill/phase/retest artifacts under the root.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the reported artifacts. Without this flag the command is dry-run only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root
    if not root.exists():
        raise SystemExit(f"Root does not exist: {root}")

    debug_cutoff = utc_now() - timedelta(days=args.debug_retention_days)
    experiment_cutoff = utc_now() - timedelta(days=args.experiment_retention_days)

    candidates = [
        *iter_debug_candidates(root, cutoff=debug_cutoff),
        *iter_experiment_candidates(root, cutoff=experiment_cutoff),
    ]

    if not candidates:
        print("No cleanup candidates found.")
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: {len(candidates)} cleanup candidate(s) under {root}")
    for candidate in candidates:
        print(f"- {candidate.path} :: {candidate.reason}")
        if args.apply:
            remove_path(candidate.path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
