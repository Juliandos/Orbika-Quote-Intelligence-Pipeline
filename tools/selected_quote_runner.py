#!/usr/bin/env python3
"""Run existing quote processors against a selected subset of quote files."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.supplier_quote_matcher import DEFAULT_DAILY_REPORT_DIR, DEFAULT_QUOTES_DIR, rebuild_daily_reports

DEFAULT_TRACE_DIR = Path("local/orbika_incremental/agentic_traces")
REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("supplier_matching", "agentic_review"), required=True)
    parser.add_argument("--quotes-dir", type=Path, default=DEFAULT_QUOTES_DIR)
    parser.add_argument("--daily-report-dir", type=Path, default=DEFAULT_DAILY_REPORT_DIR)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--limit-per-part", type=int, default=5)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--disable-traces", action="store_true")
    parser.add_argument("--quote-key", dest="quote_keys", action="append", required=True)
    return parser.parse_args(argv)


def require_quote_paths(quotes_dir: Path, quote_keys: list[str]) -> list[Path]:
    paths: list[Path] = []
    missing: list[str] = []
    for key in quote_keys:
        path = quotes_dir / f"{key}.json"
        if path.exists():
            paths.append(path)
        else:
            missing.append(key)
    if missing:
        raise SystemExit(f"Missing quote files: {', '.join(missing)}")
    return paths


def copy_back(staged_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in staged_dir.glob("*.json"):
        shutil.copy2(path, target_dir / path.name)


def run_subprocess(command: list[str]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    completed = subprocess.run(command, cwd=str(REPO_ROOT), env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    source_quotes_dir = args.quotes_dir
    selected_paths = require_quote_paths(source_quotes_dir, args.quote_keys)

    with tempfile.TemporaryDirectory(prefix="orbika-selected-") as temp_root_str:
        temp_root = Path(temp_root_str)
        staged_quotes_dir = temp_root / "quotes"
        staged_quotes_dir.mkdir(parents=True, exist_ok=True)
        for path in selected_paths:
            shutil.copy2(path, staged_quotes_dir / path.name)

        if args.mode == "supplier_matching":
            temp_daily_dir = temp_root / "daily"
            command = [
                sys.executable,
                "tools/supplier_quote_matcher.py",
                "--quotes-dir",
                str(staged_quotes_dir),
                "--daily-report-dir",
                str(temp_daily_dir),
                "--limit-per-part",
                str(args.limit_per_part),
            ]
            run_subprocess(command)
            copy_back(staged_quotes_dir, source_quotes_dir)
            rebuild_daily_reports(source_quotes_dir, args.daily_report_dir)
            return 0

        temp_trace_dir = temp_root / "agentic_traces"
        command = [
            sys.executable,
            "tools/agentic_match_reviewer.py",
            "--quotes-dir",
            str(staged_quotes_dir),
            "--limit-per-part",
            str(args.limit_per_part),
        ]
        if args.model:
            command.extend(["--model", args.model])
        if args.disable_traces:
            command.append("--disable-traces")
        else:
            command.extend(["--trace-dir", str(temp_trace_dir)])

        run_subprocess(command)
        copy_back(staged_quotes_dir, source_quotes_dir)
        if not args.disable_traces and temp_trace_dir.exists():
            args.trace_dir.mkdir(parents=True, exist_ok=True)
            for trace_path in temp_trace_dir.glob("*.json"):
                shutil.copy2(trace_path, args.trace_dir / trace_path.name)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
