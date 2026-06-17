from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import (
    AGENTIC_TRACES_DIR,
    DAILY_DIR,
    DEFAULT_GMAIL_CREDENTIALS,
    DEFAULT_GMAIL_TOKEN_CACHE,
    DEFAULT_ORBIKA_STORAGE_STATE,
    QUOTES_DIR,
    REPO_ROOT,
    STATE_PATH,
    TASK_LOG_DIR,
)
from .events import EventBus
from .quote_store import build_dashboard, list_quotes, load_state


@dataclass
class TaskRecord:
    id: str
    kind: str
    command: list[str]
    created_at: float
    status: str = "starting"
    pid: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    log_path: str | None = None
    singleton_key: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class TaskManager:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._watcher_thread = threading.Thread(target=self._watch_quotes_loop, daemon=True)
        self._watcher_thread.start()

    def tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(task) for task in sorted(self._tasks.values(), key=lambda item: item.created_at, reverse=True)]

    def active_task(self, singleton_key: str) -> TaskRecord | None:
        with self._lock:
            for task in self._tasks.values():
                if task.singleton_key == singleton_key and task.status in {"starting", "running"}:
                    return task
        return None

    def start_incremental_runner(
        self,
        *,
        poll_seconds: int = 300,
        max_results: int = 50,
        timeout_ms: int = 45000,
        max_retries: int = 4,
        headed: bool = False,
        gmail_date: str | None = None,
        allow_login_fallback: bool = False,
    ) -> dict[str, Any]:
        command = [
            "uv",
            "run",
            "--with",
            "google-api-python-client",
            "--with",
            "google-auth-oauthlib",
            "--with",
            "playwright",
            "python",
            "tools/incremental_orbika_quote_runner.py",
            "--credentials",
            DEFAULT_GMAIL_CREDENTIALS,
            "--token-cache",
            DEFAULT_GMAIL_TOKEN_CACHE,
            "--storage-state",
            DEFAULT_ORBIKA_STORAGE_STATE,
            "--max-results",
            str(max_results),
            "--timeout-ms",
            str(timeout_ms),
            "--max-retries",
            str(max_retries),
            "--poll-seconds",
            str(poll_seconds),
        ]
        if gmail_date:
            command.extend(["--gmail-date", gmail_date])
        if headed:
            command.append("--headed")
        if allow_login_fallback:
            command.append("--allow-login-fallback")
        return self._start_task(
            kind="incremental_runner",
            command=command,
            singleton_key="incremental_runner",
            meta={
                "poll_seconds": poll_seconds,
                "gmail_date": gmail_date,
                "headed": headed,
                "allow_login_fallback": allow_login_fallback,
            },
        )

    def stop_task(self, task_id: str) -> bool:
        with self._lock:
            process = self._processes.get(task_id)
            task = self._tasks.get(task_id)
        if not process or not task or task.status not in {"starting", "running"}:
            return False
        process.terminate()
        self._event_bus.publish(
            "task.updated",
            {"task": asdict(task), "message": "Termination requested."},
        )
        return True

    def run_supplier_matching(self, limit_per_part: int = 5) -> dict[str, Any]:
        command = self._supplier_matching_command(limit_per_part=limit_per_part, quote_keys=None)
        return self._start_task(
            kind="supplier_matching",
            command=command,
            singleton_key="supplier_matching",
            meta={"limit_per_part": limit_per_part},
        )

    def run_supplier_matching_selection(
        self,
        *,
        quote_keys: list[str],
        limit_per_part: int = 5,
    ) -> dict[str, Any]:
        command = self._supplier_matching_command(limit_per_part=limit_per_part, quote_keys=quote_keys)
        return self._start_task(
            kind="supplier_matching_selection",
            command=command,
            singleton_key=None,
            meta={"limit_per_part": limit_per_part, "quote_keys": quote_keys},
        )

    def run_agentic_review(
        self,
        *,
        limit_per_part: int = 5,
        model: str | None = None,
        disable_traces: bool = False,
    ) -> dict[str, Any]:
        command = self._agentic_review_command(
            limit_per_part=limit_per_part,
            model=model,
            disable_traces=disable_traces,
            quote_keys=None,
        )
        return self._start_task(
            kind="agentic_review",
            command=command,
            singleton_key="agentic_review",
            meta={"limit_per_part": limit_per_part, "model": model, "disable_traces": disable_traces},
        )

    def run_agentic_review_selection(
        self,
        *,
        quote_keys: list[str],
        limit_per_part: int = 5,
        model: str | None = None,
        disable_traces: bool = False,
    ) -> dict[str, Any]:
        command = self._agentic_review_command(
            limit_per_part=limit_per_part,
            model=model,
            disable_traces=disable_traces,
            quote_keys=quote_keys,
        )
        return self._start_task(
            kind="agentic_review_selection",
            command=command,
            singleton_key=None,
            meta={
                "limit_per_part": limit_per_part,
                "model": model,
                "disable_traces": disable_traces,
                "quote_keys": quote_keys,
            },
        )

    def _supplier_matching_command(
        self,
        *,
        limit_per_part: int,
        quote_keys: list[str] | None,
    ) -> list[str]:
        if quote_keys:
            command = [
                "uv",
                "run",
                "python",
                "tools/selected_quote_runner.py",
                "--mode",
                "supplier_matching",
                "--quotes-dir",
                str(QUOTES_DIR),
                "--daily-report-dir",
                str(DAILY_DIR),
                "--limit-per-part",
                str(limit_per_part),
            ]
            for quote_key in quote_keys:
                command.extend(["--quote-key", quote_key])
            return command
        return [
            "uv",
            "run",
            "python",
            "tools/supplier_quote_matcher.py",
            "--quotes-dir",
            str(QUOTES_DIR),
            "--daily-report-dir",
            str(DAILY_DIR),
            "--limit-per-part",
            str(limit_per_part),
        ]

    def _agentic_review_command(
        self,
        *,
        limit_per_part: int,
        model: str | None,
        disable_traces: bool,
        quote_keys: list[str] | None,
    ) -> list[str]:
        if quote_keys:
            command = [
                "uv",
                "run",
                "python",
                "tools/selected_quote_runner.py",
                "--mode",
                "agentic_review",
                "--quotes-dir",
                str(QUOTES_DIR),
                "--trace-dir",
                str(AGENTIC_TRACES_DIR),
                "--limit-per-part",
                str(limit_per_part),
            ]
            for quote_key in quote_keys:
                command.extend(["--quote-key", quote_key])
        else:
            command = [
                "uv",
                "run",
                "python",
                "tools/agentic_match_reviewer.py",
                "--quotes-dir",
                str(QUOTES_DIR),
                "--limit-per-part",
                str(limit_per_part),
            ]
        if model:
            command.extend(["--model", model])
        if disable_traces:
            command.append("--disable-traces")
        elif quote_keys:
            command.extend(["--trace-dir", str(AGENTIC_TRACES_DIR)])
        elif not quote_keys:
            command.extend(["--trace-dir", str(AGENTIC_TRACES_DIR)])
        return command

    def _start_task(
        self,
        *,
        kind: str,
        command: list[str],
        singleton_key: str | None,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.active_task(singleton_key) if singleton_key else None
        if existing is not None:
            return asdict(existing)

        task_id = str(uuid.uuid4())
        log_path = TASK_LOG_DIR / f"{task_id}.log"
        task = TaskRecord(
            id=task_id,
            kind=kind,
            command=command,
            created_at=time.time(),
            log_path=str(log_path),
            singleton_key=singleton_key,
            meta=meta,
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = "."
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        task.pid = process.pid
        task.started_at = time.time()
        task.status = "running"
        with self._lock:
            self._tasks[task_id] = task
            self._processes[task_id] = process
        self._event_bus.publish("task.started", {"task": asdict(task)})
        threading.Thread(
            target=self._stream_output,
            args=(task_id, process, log_path),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._wait_for_completion,
            args=(task_id, process),
            daemon=True,
        ).start()
        return asdict(task)

    def _stream_output(self, task_id: str, process: subprocess.Popen[str], log_path: Path) -> None:
        assert process.stdout is not None
        with log_path.open("a", encoding="utf-8") as handle:
            for line in process.stdout:
                rendered = line.rstrip()
                handle.write(rendered + "\n")
                self._event_bus.publish(
                    "task.log",
                    {"task_id": task_id, "line": rendered},
                )

    def _wait_for_completion(self, task_id: str, process: subprocess.Popen[str]) -> None:
        exit_code = process.wait()
        with self._lock:
            task = self._tasks[task_id]
            task.exit_code = exit_code
            task.finished_at = time.time()
            task.status = "completed" if exit_code == 0 else "failed"
            self._processes.pop(task_id, None)
        self._event_bus.publish(
            "task.completed" if exit_code == 0 else "task.failed",
            {"task": asdict(task), "dashboard": build_dashboard(), "tasks": self.tasks()},
        )

    def _watch_quotes_loop(self) -> None:
        last_quote_keys = {item["quote_key"] for item in list_quotes()}
        last_state_updated = load_state().get("updated_at")
        while True:
            try:
                quotes = list_quotes()
                current_keys = {item["quote_key"] for item in quotes}
                new_keys = sorted(current_keys - last_quote_keys)
                if new_keys:
                    for key in new_keys:
                        quote = next((item for item in quotes if item["quote_key"] == key), None)
                        if quote:
                            self._event_bus.publish("quote.new", {"quote": quote})
                    self._event_bus.publish("dashboard.updated", build_dashboard())
                    last_quote_keys = current_keys

                state = load_state()
                updated_at = state.get("updated_at")
                if updated_at and updated_at != last_state_updated:
                    self._event_bus.publish(
                        "pipeline.state",
                        {"state": state, "dashboard": build_dashboard(), "tasks": self.tasks()},
                    )
                    last_state_updated = updated_at
            except Exception as exc:
                self._event_bus.publish("watcher.error", {"message": str(exc)})
            time.sleep(2)
