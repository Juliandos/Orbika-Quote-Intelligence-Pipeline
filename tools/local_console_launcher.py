#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = REPO_ROOT / "local"
RUNTIME_DIR = LOCAL_DIR / "launcher"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = RUNTIME_DIR / "state.json"
MAINTENANCE_FILE = RUNTIME_DIR / "maintenance.json"
PROVIDER_REFRESH_FILE = RUNTIME_DIR / "provider_refresh.json"
API_LOG = RUNTIME_DIR / "api.log"
WEB_LOG = RUNTIME_DIR / "web.log"

UV_CANDIDATES = [REPO_ROOT / ".venv/bin/uv", Path.home() / ".local/bin/uv"]
UV_BIN = next((candidate for candidate in UV_CANDIDATES if candidate.exists()), Path("uv"))

API_PORT = int(os.environ.get("ORBIKA_API_PORT", "8001"))
WEB_PORT = int(os.environ.get("ORBIKA_WEB_PORT", "3000"))
DB_PORT = int(os.environ.get("ORBIKA_POSTGRES_PORT", "5433"))
DB_NAME = os.environ.get("ORBIKA_POSTGRES_DB", "orbika_local")
DB_USER = os.environ.get("ORBIKA_POSTGRES_USER", "orbika")
DB_PASSWORD = os.environ.get("ORBIKA_POSTGRES_PASSWORD", "orbika_local_dev_password")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@localhost:{DB_PORT}/{DB_NAME}",
)
API_BASE = f"http://127.0.0.1:{API_PORT}"
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"
DEFAULT_SUPERVISION_STALE_SECONDS = int(os.environ.get("ORBIKA_RUNNER_STALE_SECONDS", "900"))

DEFAULT_GMAIL_CREDENTIALS = Path(
    os.environ.get(
        "GMAIL_OAUTH_CLIENT_SECRET",
        str(Path.home() / ".config" / "openclaw" / "gmail" / "autolujoslaser1-client-secret.json"),
    )
)
DEFAULT_GMAIL_TOKEN_CACHE = Path.home() / ".cache" / "openclaw" / "gmail_quote_extractor" / "autolujoslaser1-token.json"
DEFAULT_ORBIKA_STORAGE_STATE = Path.home() / ".cache" / "openclaw" / "orbika_quote_extractor" / "storage-state.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def run(command: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("DATABASE_URL", DATABASE_URL)
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=check,
        text=True,
        capture_output=capture,
        env=env,
    )


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def wait_for_port(port: int, *, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(1)
    return False


def wait_for_http(url: str, *, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return True
        except (HTTPError, URLError, TimeoutError):
            time.sleep(1)
    return False


def http_json(url: str, *, timeout: float = 4.0) -> Any:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ps_command(pid: int) -> str:
    proc_path = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = proc_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
    except OSError:
        return ""
    return raw


def process_alive(pid: int, *, expected_markers: list[str] | None = None) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if expected_markers:
        command = ps_command(pid).lower()
        if not command:
            return False
        return all(marker.lower() in command for marker in expected_markers)
    return True


def read_state() -> dict[str, Any]:
    return read_json_file(STATE_FILE)


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_state(payload: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def maintenance_report() -> dict[str, Any]:
    report = read_json_file(MAINTENANCE_FILE)
    if report:
        return report
    return {
        "status": "not_run",
        "generated_at": None,
        "policy": {},
        "local": {"candidate_count": 0, "deleted_count": 0, "candidates": []},
        "database": {"enabled": False, "reason": "maintenance no ejecutado todavia"},
        "summary": {"local_deleted": 0, "local_candidates": 0, "database_deleted": 0, "database_enabled": False},
    }


def provider_refresh_report() -> dict[str, Any]:
    report = read_json_file(PROVIDER_REFRESH_FILE)
    if report:
        return report
    return {
        "status": "not_run",
        "generated_at": None,
        "matching": {"status": "not_run"},
        "agentic_review": {"status": "not_run"},
        "postgres_sync": {"enabled": False},
        "summary": {"quotes_seen": 0, "quotes_with_provider": 0, "quotes_with_agentic": 0},
        "message": "El refresco semanal todavia no se ha ejecutado.",
    }


def api_process_command() -> str:
    return (
        "exec env "
        f"DATABASE_URL={shlex.quote(DATABASE_URL)} "
        "ORBIKA_API_STORE=postgres "
        "PYTHONPATH=. "
        f"{shlex.quote(str(UV_BIN))} run uvicorn --app-dir apps/api orbika_console_api.main:app --host 0.0.0.0 --port {API_PORT}"
    )


def web_process_command() -> str:
    return (
        "source ~/.nvm/nvm.sh >/dev/null 2>&1 && "
        "nvm use 22 >/dev/null && "
        "cd apps/web && "
        "exec env "
        f"NEXT_PUBLIC_API_BASE_URL=http://localhost:{API_PORT} "
        f"npm run dev -- --hostname 0.0.0.0 --port {WEB_PORT}"
    )


def spawn_shell(command: str, *, log_path: Path) -> int:
    handle = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=REPO_ROOT,
        text=True,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process.pid


def docker_exec_pg_isready() -> bool:
    try:
        result = run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "pg_isready",
                "-U",
                DB_USER,
                "-d",
                DB_NAME,
            ]
        )
    except subprocess.CalledProcessError:
        return False
    return "accepting connections" in (result.stdout or "")


def ensure_db_started() -> None:
    run(["docker", "compose", "up", "-d", "db"])
    deadline = time.time() + 90
    while time.time() < deadline:
        if docker_exec_pg_isready():
            return
        time.sleep(2)
    raise SystemExit("PostgreSQL no quedo saludable en el tiempo esperado.")


def apply_migrations() -> None:
    run(
        [
            str(UV_BIN),
            "run",
            "--with",
            "alembic",
            "--with",
            "psycopg[binary]",
            "alembic",
            "upgrade",
            "head",
        ],
        check=True,
    )


def stop_runner_if_possible() -> None:
    if not wait_for_http(f"{API_BASE}/api/health", timeout=3):
        return
    try:
        tasks = http_json(f"{API_BASE}/api/tasks", timeout=4)
    except Exception:
        return
    for task in tasks:
        if task.get("kind") == "incremental_runner" and task.get("status") in {"starting", "running"}:
            task_id = task.get("id")
            if not task_id:
                continue
            try:
                request = Request(
                    f"{API_BASE}/api/tasks/{task_id}/stop",
                    method="POST",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                urlopen(request, timeout=4).read()
            except Exception:
                continue


def terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + 15
    while time.time() < deadline:
        if not process_alive(pid):
            return
        time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def preflight() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("repo", REPO_ROOT.exists(), str(REPO_ROOT))
    add("docker", shutil_which("docker"), "docker compose disponible en WSL" if shutil_which("docker") else "docker no esta disponible")
    add("uv", UV_BIN.exists() if UV_BIN != Path("uv") else shutil_which("uv"), f"uv disponible en {UV_BIN}" if (UV_BIN.exists() if UV_BIN != Path("uv") else shutil_which("uv")) else "uv no esta disponible")
    add("python3", shutil_which("python3"), "python3 disponible" if shutil_which("python3") else "python3 no esta disponible")
    add("npm", bool(command_available("source ~/.nvm/nvm.sh >/dev/null 2>&1 && nvm use 22 >/dev/null && command -v npm")), "npm disponible via nvm" if command_available("source ~/.nvm/nvm.sh >/dev/null 2>&1 && nvm use 22 >/dev/null && command -v npm") else "npm no esta disponible via nvm")
    add("node_modules", (REPO_ROOT / "apps/web/node_modules/next/package.json").exists(), "apps/web/node_modules instalado")
    add("gmail_credentials", DEFAULT_GMAIL_CREDENTIALS.exists(), str(DEFAULT_GMAIL_CREDENTIALS))
    add("gmail_token_cache", DEFAULT_GMAIL_TOKEN_CACHE.exists(), str(DEFAULT_GMAIL_TOKEN_CACHE))
    add("orbika_storage_state", DEFAULT_ORBIKA_STORAGE_STATE.exists(), str(DEFAULT_ORBIKA_STORAGE_STATE))
    add("api_port_state", True, f"puerto {API_PORT} libre" if not port_open(API_PORT) else f"puerto {API_PORT} ya esta en uso")
    add("web_port_state", True, f"puerto {WEB_PORT} libre" if not port_open(WEB_PORT) else f"puerto {WEB_PORT} ya esta en uso")

    overall_ok = all(item["ok"] for item in checks if item["name"] not in {"gmail_token_cache", "orbika_storage_state"})
    return {"ok": overall_ok, "checks": checks}


def command_available(command: str) -> bool:
    completed = subprocess.run(
        ["bash", "-lc", command],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    return completed.returncode == 0


def shutil_which(command: str) -> bool:
    from shutil import which

    return which(command) is not None


def supervision_status() -> dict[str, Any]:
    supervision: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "status": "warning",
        "status_label": "Sin comprobar",
        "message": "La supervision del runner aun no ha podido consultar la API.",
        "runner_active": False,
        "runner_stage": None,
        "pipeline_updated_at": None,
        "is_stale": False,
        "stale_threshold_seconds": DEFAULT_SUPERVISION_STALE_SECONDS,
        "recent_failed_tasks": 0,
        "recovery_actions": ["Abre la consola y valida que la API este disponible."],
    }

    if not wait_for_http(f"{API_BASE}/api/health", timeout=1):
        supervision.update(
            {
                "status": "error",
                "status_label": "API no disponible",
                "message": "La API local no esta respondiendo; no se puede supervisar el runner todavia.",
                "recovery_actions": [
                    "Inicia la consola desde Windows o ejecuta el launcher local.",
                    "Si el problema persiste, revisa local/launcher/api.log.",
                ],
            }
        )
        return supervision

    try:
        tasks = http_json(f"{API_BASE}/api/tasks", timeout=4)
        state = http_json(f"{API_BASE}/api/pipeline/state", timeout=4)
    except Exception as exc:  # noqa: BLE001
        supervision.update(
            {
                "status": "warning",
                "status_label": "Supervision incompleta",
                "message": f"La API esta arriba, pero no se pudo leer el estado del pipeline: {exc}",
                "recovery_actions": ["Actualiza el tablero y revisa el panel de actividad."],
            }
        )
        return supervision

    runner_task = next(
        (
            task
            for task in tasks
            if task.get("kind") == "incremental_runner" and task.get("status") in {"starting", "running"}
        ),
        None,
    )
    failed_tasks = [task for task in tasks if task.get("kind") == "incremental_runner" and task.get("status") == "failed"]
    updated_at = state.get("updated_at")
    updated_dt = parse_iso_datetime(updated_at)
    age_seconds = None
    if updated_dt is not None:
        age_seconds = max((datetime.now(timezone.utc) - updated_dt).total_seconds(), 0)

    supervision.update(
        {
            "runner_active": runner_task is not None,
            "runner_stage": state.get("stage"),
            "pipeline_updated_at": updated_at,
            "recent_failed_tasks": len(failed_tasks),
            "is_stale": bool(runner_task and age_seconds is not None and age_seconds > DEFAULT_SUPERVISION_STALE_SECONDS),
        }
    )

    if runner_task and supervision["is_stale"]:
        supervision.update(
            {
                "status": "warning",
                "status_label": "Runner desactualizado",
                "message": "El runner sigue marcado como activo, pero el estado no cambia desde hace varios minutos.",
                "recovery_actions": [
                    "Deten el runner desde la UI y vuelve a iniciarlo.",
                    "Si vuelve a quedarse quieto, revisa el panel de actividad y local/launcher/api.log.",
                ],
            }
        )
    elif runner_task:
        supervision.update(
            {
                "status": "healthy",
                "status_label": "Runner saludable",
                "message": "El runner esta escuchando correos y el estado del pipeline se sigue actualizando.",
                "recovery_actions": ["No hace falta intervenir mientras sigan entrando actualizaciones."],
            }
        )
    elif failed_tasks:
        supervision.update(
            {
                "status": "warning",
                "status_label": "Runner detenido con fallos previos",
                "message": "El runner no esta activo y hay fallos recientes registrados en tareas anteriores.",
                "recovery_actions": [
                    "Revisa el panel de actividad para ver el ultimo error.",
                    "Cuando corrijas la causa, inicia de nuevo el modo Esperar correos.",
                ],
            }
        )
    else:
        supervision.update(
            {
                "status": "idle",
                "status_label": "Runner en pausa",
                "message": "La consola esta disponible, pero el runner no esta esperando correos en este momento.",
                "recovery_actions": ["Usa el boton Esperar correos cuando quieras dejar la cola escuchando nuevas entradas."],
            }
        )

    return supervision


def status() -> dict[str, Any]:
    state = read_state()
    api_pid = int(state.get("api_pid") or 0)
    web_pid = int(state.get("web_pid") or 0)
    return {
        "db_port_open": port_open(DB_PORT),
        "api_port_open": port_open(API_PORT),
        "web_port_open": port_open(WEB_PORT),
        "api_healthy": wait_for_http(f"{API_BASE}/api/health", timeout=1),
        "web_healthy": wait_for_http(WEB_URL, timeout=1),
        "api_pid_running": api_pid > 0 and process_alive(api_pid, expected_markers=["orbika_console_api.main:app"]),
        "web_pid_running": web_pid > 0 and process_alive(web_pid, expected_markers=["next", "dev"]),
        "maintenance": maintenance_report(),
        "provider_refresh": provider_refresh_report(),
        "supervision": supervision_status(),
        "state_file": str(STATE_FILE),
        "launcher_started_at": state.get("started_at"),
    }


def start() -> dict[str, Any]:
    result = preflight()
    if not result["ok"]:
        raise SystemExit(json.dumps(result, indent=2, ensure_ascii=True))

    current = status()
    if current["api_port_open"] and not current["api_healthy"] and not current["api_pid_running"]:
        raise SystemExit("El puerto 8001 esta ocupado por otro proceso o una API no saludable.")
    if current["web_port_open"] and not current["web_healthy"] and not current["web_pid_running"]:
        raise SystemExit("El puerto 3000 esta ocupado por otro proceso o un frontend no saludable.")

    ensure_db_started()
    apply_migrations()

    state = read_state()
    api_pid = int(state.get("api_pid") or 0)
    web_pid = int(state.get("web_pid") or 0)

    api_ready = current["api_port_open"] and current["api_healthy"]
    web_ready = current["web_port_open"] and current["web_healthy"]

    if not api_ready:
        if not (api_pid > 0 and process_alive(api_pid, expected_markers=["orbika_console_api.main:app"]) and wait_for_http(f"{API_BASE}/api/health", timeout=1)):
            api_pid = spawn_shell(api_process_command(), log_path=API_LOG)
    else:
        api_pid = api_pid if api_pid > 0 else 0
    if not wait_for_port(API_PORT, timeout=60) or not wait_for_http(f"{API_BASE}/api/health", timeout=60):
        raise SystemExit("La API no respondio correctamente en el puerto 8001.")

    if not web_ready:
        if not (web_pid > 0 and process_alive(web_pid, expected_markers=["next", "dev"]) and wait_for_http(WEB_URL, timeout=1)):
            web_pid = spawn_shell(web_process_command(), log_path=WEB_LOG)
    else:
        web_pid = web_pid if web_pid > 0 else 0
    if not wait_for_port(WEB_PORT, timeout=90) or not wait_for_http(WEB_URL, timeout=90):
        raise SystemExit("El frontend no respondio correctamente en el puerto 3000.")

    payload = {
        "started_at": time.time(),
        "api_pid": api_pid,
        "web_pid": web_pid,
        "api_url": API_BASE,
        "web_url": WEB_URL,
        "database_url": DATABASE_URL,
        "logs": {"api": str(API_LOG), "web": str(WEB_LOG)},
    }
    write_state(payload)
    return payload


def stop(*, stop_db: bool = True) -> dict[str, Any]:
    stop_runner_if_possible()
    state = read_state()
    api_pid = int(state.get("api_pid") or 0)
    web_pid = int(state.get("web_pid") or 0)

    if web_pid > 0 and process_alive(web_pid, expected_markers=["next", "dev"]):
        terminate_pid(web_pid)
    if api_pid > 0 and process_alive(api_pid, expected_markers=["orbika_console_api.main:app"]):
        terminate_pid(api_pid)

    if stop_db:
        try:
            run(["docker", "compose", "stop", "db"], check=False)
        except Exception:
            pass

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return {"ok": True, "stopped_db": stop_db}


def maintenance(*, apply: bool = False) -> dict[str, Any]:
    command = [
        str(UV_BIN),
        "run",
        "--with",
        "psycopg[binary]",
        "python",
        "-m",
        "tools.maintenance_retention",
        "--root",
        str(LOCAL_DIR / "orbika_incremental"),
        "--runtime-dir",
        str(RUNTIME_DIR),
        "--report-file",
        str(MAINTENANCE_FILE),
    ]
    if apply:
        command.append("--apply")
    run(command, check=True)
    return maintenance_report()


def provider_refresh(*, limit_per_part: int = 5) -> dict[str, Any]:
    command = [
        str(UV_BIN),
        "run",
        "--with",
        "psycopg[binary]",
        "python",
        "tools/provider_refresh.py",
        "--quotes-dir",
        str(LOCAL_DIR / "orbika_incremental" / "quotes"),
        "--daily-report-dir",
        str(LOCAL_DIR / "orbika_incremental" / "daily"),
        "--trace-dir",
        str(LOCAL_DIR / "orbika_incremental" / "agentic_traces"),
        "--report-file",
        str(PROVIDER_REFRESH_FILE),
        "--limit-per-part",
        str(limit_per_part),
    ]
    run(command, check=True)
    return provider_refresh_report()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows-friendly local launcher for the Orbika console.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    subparsers.add_parser("status")
    subparsers.add_parser("start")
    maintenance_parser = subparsers.add_parser("maintenance")
    maintenance_parser.add_argument("--apply", action="store_true", help="Delete expired rows and artifacts instead of only reporting them.")
    provider_refresh_parser = subparsers.add_parser("provider-refresh")
    provider_refresh_parser.add_argument("--limit-per-part", type=int, default=5, help="Maximum provider candidates reviewed per part during the weekly refresh.")
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--keep-db", action="store_true", help="Do not stop the PostgreSQL container.")

    args = parser.parse_args(argv)
    if args.command == "preflight":
        print(json.dumps(preflight(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "start":
        print(json.dumps(start(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "maintenance":
        print(json.dumps(maintenance(apply=args.apply), indent=2, ensure_ascii=True))
        return 0
    if args.command == "provider-refresh":
        print(json.dumps(provider_refresh(limit_per_part=args.limit_per_part), indent=2, ensure_ascii=True))
        return 0
    if args.command == "stop":
        print(json.dumps(stop(stop_db=not args.keep_db), indent=2, ensure_ascii=True))
        return 0
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
