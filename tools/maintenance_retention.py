#!/usr/bin/env python3
"""Periodic maintenance and retention for local Orbika operation.

This command keeps the local workspace lean without touching active work:
- removes stale debug and experiment artifacts under ``local/orbika_incremental``
- prunes launcher logs older than the retention window
- optionally removes expired PostgreSQL rows using the configured ``DATABASE_URL``

The command is safe by default and writes a machine-readable report so the
launcher and the UI can expose the latest maintenance status.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.cleanup_incremental_outputs import (
    CleanupCandidate,
    iter_debug_candidates,
    iter_experiment_candidates,
    is_older_than,
    remove_path,
    utc_now,
)
from tools.postgres_quote_persistence import database_url_from_env


DEFAULT_ROOT = Path("local/orbika_incremental")
DEFAULT_RUNTIME_DIR = Path("local/launcher")
DEFAULT_REPORT_FILE = DEFAULT_RUNTIME_DIR / "maintenance.json"

ACTIVE_QUOTE_STATUSES = {
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
    "needs_retry",
}

TERMINAL_QUOTE_STATUSES = {"quoted", "sent", "failed", "archived"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "blocked"}


@dataclass
class RetentionPolicy:
    quote_retention_days: int = 90
    task_retention_days: int = 30
    log_retention_days: int = 30
    debug_retention_days: int = 7
    experiment_retention_days: int = 7


def iter_launcher_log_candidates(runtime_dir: Path, *, cutoff: datetime) -> list[CleanupCandidate]:
    candidates: list[CleanupCandidate] = []
    if not runtime_dir.exists():
        return candidates
    for child in sorted(runtime_dir.glob("*.log")):
        if child.is_file() and is_older_than(child, cutoff=cutoff):
            candidates.append(CleanupCandidate(child, "launcher log older than retention"))
    return candidates


def collect_local_candidates(root: Path, runtime_dir: Path, policy: RetentionPolicy) -> list[CleanupCandidate]:
    now = utc_now()
    debug_cutoff = now - timedelta(days=policy.debug_retention_days)
    experiment_cutoff = now - timedelta(days=policy.experiment_retention_days)
    log_cutoff = now - timedelta(days=policy.log_retention_days)
    candidates = [
        *iter_debug_candidates(root, cutoff=debug_cutoff),
        *iter_experiment_candidates(root, cutoff=experiment_cutoff),
        *iter_launcher_log_candidates(runtime_dir, cutoff=log_cutoff),
    ]
    unique: list[CleanupCandidate] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate.path in seen:
            continue
        seen.add(candidate.path)
        unique.append(candidate)
    return unique


def _delete_candidates(candidates: list[CleanupCandidate]) -> int:
    deleted = 0
    for candidate in candidates:
        if candidate.path.exists():
            remove_path(candidate.path)
            deleted += 1
    return deleted


def _database_summary_counts(database_url: str, policy: RetentionPolicy) -> dict[str, Any]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - exercised through launcher context
        return {"enabled": False, "reason": f"psycopg no disponible: {exc}"}

    now = utc_now()
    quote_cutoff = now - timedelta(days=policy.quote_retention_days)
    task_cutoff = now - timedelta(days=policy.task_retention_days)
    log_cutoff = now - timedelta(days=policy.log_retention_days)

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS count
            FROM quotes
            WHERE created_at < %s
              AND status = ANY(%s)
            """,
            (quote_cutoff, sorted(TERMINAL_QUOTE_STATUSES)),
        )
        quotes_expired = int(cur.fetchone()["count"])

        cur.execute(
            """
            SELECT count(*) AS count
            FROM quotes
            WHERE created_at < %s
              AND status = ANY(%s)
            """,
            (quote_cutoff, sorted(ACTIVE_QUOTE_STATUSES)),
        )
        quotes_protected = int(cur.fetchone()["count"])

        cur.execute(
            """
            SELECT count(*) AS count
            FROM emails e
            WHERE COALESCE(e.received_at, e.created_at) < %s
              AND NOT EXISTS (
                SELECT 1
                FROM quotes q
                WHERE q.email_id = e.id
              )
            """,
            (quote_cutoff,),
        )
        emails_expired = int(cur.fetchone()["count"])

        cur.execute(
            """
            SELECT count(*) AS count
            FROM events
            WHERE created_at < %s
            """,
            (log_cutoff,),
        )
        events_expired = int(cur.fetchone()["count"])

        cur.execute(
            """
            SELECT count(*) AS count
            FROM tasks
            WHERE COALESCE(finished_at, created_at) < %s
              AND status = ANY(%s)
            """,
            (task_cutoff, sorted(TERMINAL_TASK_STATUSES)),
        )
        tasks_expired = int(cur.fetchone()["count"])

    return {
        "enabled": True,
        "quote_cutoff": quote_cutoff.isoformat(),
        "task_cutoff": task_cutoff.isoformat(),
        "log_cutoff": log_cutoff.isoformat(),
        "quotes_expired": quotes_expired,
        "quotes_protected": quotes_protected,
        "emails_expired": emails_expired,
        "events_expired": events_expired,
        "tasks_expired": tasks_expired,
    }


def _delete_database_expired_rows(database_url: str, policy: RetentionPolicy) -> dict[str, Any]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - exercised through launcher context
        return {"enabled": False, "reason": f"psycopg no disponible: {exc}"}

    now = utc_now()
    quote_cutoff = now - timedelta(days=policy.quote_retention_days)
    task_cutoff = now - timedelta(days=policy.task_retention_days)
    log_cutoff = now - timedelta(days=policy.log_retention_days)

    def delete_count(cur: Any, statement: str, params: tuple[Any, ...]) -> int:
        cur.execute(statement, params)
        row = cur.fetchone()
        if row is None:
            return 0
        return int(row["deleted"])

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
        quote_events_deleted = delete_count(
            cur,
            """
            WITH expired_quotes AS (
              SELECT id
              FROM quotes
              WHERE created_at < %s
                AND status = ANY(%s)
            ),
            deleted_events AS (
              DELETE FROM events
              WHERE quote_id IN (SELECT id FROM expired_quotes)
              RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted_events
            """,
            (quote_cutoff, sorted(TERMINAL_QUOTE_STATUSES)),
        )
        quotes_deleted = delete_count(
            cur,
            """
            WITH expired_quotes AS (
              SELECT id
              FROM quotes
              WHERE created_at < %s
                AND status = ANY(%s)
            ),
            deleted_quotes AS (
              DELETE FROM quotes
              WHERE id IN (SELECT id FROM expired_quotes)
              RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted_quotes
            """,
            (quote_cutoff, sorted(TERMINAL_QUOTE_STATUSES)),
        )
        task_events_deleted = delete_count(
            cur,
            """
            WITH expired_tasks AS (
              SELECT id
              FROM tasks
              WHERE COALESCE(finished_at, created_at) < %s
                AND status = ANY(%s)
            ),
            deleted_events AS (
              DELETE FROM events
              WHERE task_id IN (SELECT id FROM expired_tasks)
              RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted_events
            """,
            (task_cutoff, sorted(TERMINAL_TASK_STATUSES)),
        )
        tasks_deleted = delete_count(
            cur,
            """
            WITH expired_tasks AS (
              SELECT id
              FROM tasks
              WHERE COALESCE(finished_at, created_at) < %s
                AND status = ANY(%s)
            ),
            deleted_tasks AS (
              DELETE FROM tasks
              WHERE id IN (SELECT id FROM expired_tasks)
              RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted_tasks
            """,
            (task_cutoff, sorted(TERMINAL_TASK_STATUSES)),
        )
        events_deleted = delete_count(
            cur,
            """
            WITH deleted_events AS (
              DELETE FROM events
              WHERE created_at < %s
              RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted_events
            """,
            (log_cutoff,),
        )
        emails_deleted = delete_count(
            cur,
            """
            WITH expired_emails AS (
              SELECT e.id
              FROM emails e
              WHERE COALESCE(e.received_at, e.created_at) < %s
                AND NOT EXISTS (
                  SELECT 1
                  FROM quotes q
                  WHERE q.email_id = e.id
                )
            ),
            deleted_emails AS (
              DELETE FROM emails
              WHERE id IN (SELECT id FROM expired_emails)
              RETURNING 1
            )
            SELECT count(*) AS deleted FROM deleted_emails
            """,
            (quote_cutoff,),
        )

    return {
        "enabled": True,
        "quote_cutoff": quote_cutoff.isoformat(),
        "task_cutoff": task_cutoff.isoformat(),
        "log_cutoff": log_cutoff.isoformat(),
        "quote_events_deleted": quote_events_deleted,
        "quotes_deleted": quotes_deleted,
        "task_events_deleted": task_events_deleted,
        "tasks_deleted": tasks_deleted,
        "events_deleted": events_deleted,
        "emails_deleted": emails_deleted,
        "deleted_total": sum(
            [
                quote_events_deleted,
                quotes_deleted,
                task_events_deleted,
                tasks_deleted,
                events_deleted,
                emails_deleted,
            ]
        ),
    }


def run_maintenance(
    *,
    root: Path = DEFAULT_ROOT,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    report_file: Path = DEFAULT_REPORT_FILE,
    policy: RetentionPolicy | None = None,
    apply: bool = False,
    database_url: str | None = None,
) -> dict[str, Any]:
    policy = policy or RetentionPolicy()
    local_candidates = collect_local_candidates(root, runtime_dir, policy)
    local_deleted = _delete_candidates(local_candidates) if apply else 0

    resolved_database_url = database_url or database_url_from_env()
    if resolved_database_url:
        db_summary = _delete_database_expired_rows(resolved_database_url, policy) if apply else _database_summary_counts(resolved_database_url, policy)
    else:
        db_summary = {"enabled": False, "reason": "DATABASE_URL no esta configurada"}

    local_summary = {
        "candidate_count": len(local_candidates),
        "deleted_count": local_deleted,
        "candidates": [
            {
                "path": str(candidate.path),
                "reason": candidate.reason,
            }
            for candidate in local_candidates
        ],
    }
    report = {
        "status": "applied" if apply else "dry-run",
        "generated_at": utc_now().isoformat(),
        "policy": asdict(policy),
        "local": local_summary,
        "database": db_summary,
        "summary": {
            "local_deleted": local_deleted,
            "local_candidates": len(local_candidates),
            "database_deleted": int(db_summary.get("deleted_total") or 0),
            "database_enabled": bool(db_summary.get("enabled")),
        },
    }

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Orbika maintenance and retention.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Local Orbika incremental root.")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR, help="Directory for launcher logs.")
    parser.add_argument("--report-file", type=Path, default=DEFAULT_REPORT_FILE, help="Path for the maintenance report JSON.")
    parser.add_argument("--quote-retention-days", type=int, default=90)
    parser.add_argument("--task-retention-days", type=int, default=30)
    parser.add_argument("--log-retention-days", type=int, default=30)
    parser.add_argument("--debug-retention-days", type=int, default=7)
    parser.add_argument("--experiment-retention-days", type=int, default=7)
    parser.add_argument("--apply", action="store_true", help="Delete the expired rows and artifacts instead of only reporting them.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL for the cleanup run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    policy = RetentionPolicy(
        quote_retention_days=args.quote_retention_days,
        task_retention_days=args.task_retention_days,
        log_retention_days=args.log_retention_days,
        debug_retention_days=args.debug_retention_days,
        experiment_retention_days=args.experiment_retention_days,
    )
    report = run_maintenance(
        root=args.root,
        runtime_dir=args.runtime_dir,
        report_file=args.report_file,
        policy=policy,
        apply=args.apply,
        database_url=args.database_url,
    )
    print(
        (
            f"{report['status'].upper()}: local_deleted={report['summary']['local_deleted']} "
            f"db_deleted={report['summary']['database_deleted']} "
            f"report={args.report_file}"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
