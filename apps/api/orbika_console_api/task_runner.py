# Agrega comentarios de funcionalidad a todas las funciones
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import (
    AGENTIC_TRACES_DIR,
    API_STORE,
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

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.postgres_quote_persistence import database_url_from_env, persist_quote_files

# TaskRecord es una clase de datos que representa la información relacionada con una tarea en ejecución. Contiene campos como id, tipo de tarea, comando ejecutado, timestamps de creación, inicio y finalización, estado actual, PID del proceso asociado, ruta del archivo de log, clave de singleton para tareas exclusivas y metadatos adicionales. Esta clase se utiliza para almacenar y gestionar el estado de las tareas que se ejecutan a través del TaskManager.
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

# TaskManager es una clase que gestiona la ejecución de tareas en segundo plano, como el procesamiento de cotizaciones o la revisión agentica. Permite iniciar, monitorear y detener tareas, así como publicar eventos relacionados con el estado de las tareas y las cotizaciones. Utiliza hilos para manejar la ejecución de tareas y la supervisión de cambios en las cotizaciones.
class TaskManager:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._quote_mtimes: dict[str, float] = {
            str(path): path.stat().st_mtime for path in QUOTES_DIR.glob("*.json")
        }
        self._watcher_thread = threading.Thread(target=self._watch_quotes_loop, daemon=True)
        self._watcher_thread.start()

    # tasks es un método que devuelve una lista de diccionarios que representan las tareas actualmente gestionadas por el TaskManager. Cada diccionario contiene la información de una tarea, como su id, tipo, comando, estado, timestamps, etc. Las tareas se ordenan por fecha de creación en orden descendente (las más recientes primero). Este método se utiliza para obtener una visión general del estado de las tareas en ejecución.
    def tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(task) for task in sorted(self._tasks.values(), key=lambda item: item.created_at, reverse=True)]

    # active_task es un método que busca una tarea activa (con estado "starting" o "running") que tenga una clave de singleton específica. Si encuentra una tarea que coincide con la clave de singleton y está en estado activo, devuelve esa tarea como un objeto TaskRecord. Si no encuentra ninguna tarea activa con esa clave, devuelve None. Este método se utiliza para garantizar que solo haya una instancia activa de ciertas tareas exclusivas (singleton) en ejecución al mismo tiempo.
    def active_task(self, singleton_key: str) -> TaskRecord | None:
        with self._lock:
            for task in self._tasks.values():
                if task.singleton_key == singleton_key and task.status in {"starting", "running"}:
                    return task
        return None

    # start_incremental_runner es un método que inicia una tarea de ejecución incremental para procesar cotizaciones de manera continua. Acepta varios parámetros de configuración, como el intervalo de sondeo, el número máximo de resultados a procesar, el tiempo de espera, el número máximo de reintentos, si la ejecución debe ser con interfaz gráfica (headed), una fecha específica para filtrar correos electrónicos en Gmail y si se permite una caída a un modo de inicio de sesión alternativo. El método construye el comando para ejecutar la tarea, verifica si ya hay una tarea activa del mismo tipo (singleton) y, si no la hay, inicia la tarea utilizando el método _start_task y devuelve la información de la tarea iniciada.
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
            "--with",
            "psycopg[binary]",
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

    # stop_task es un método que intenta detener una tarea en ejecución dado su ID. Busca el proceso asociado a la tarea y, si la tarea está en estado "starting" o "running", envía una señal de terminación al proceso. Luego, publica un evento indicando que se ha solicitado la terminación de la tarea. Si la tarea no se encuentra o no está en un estado activo, devuelve False. Si la solicitud de terminación se realiza correctamente, devuelve True.
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

    # run_supplier_matching es un método que inicia una tarea de coincidencia de proveedores para procesar cotizaciones. Acepta un parámetro de configuración que especifica el número máximo de coincidencias por parte. El método construye el comando para ejecutar la tarea, verifica si ya hay una tarea activa del mismo tipo (singleton) y, si no la hay, inicia la tarea utilizando el método _start_task y devuelve la información de la tarea iniciada.
    def run_supplier_matching(self, limit_per_part: int = 5) -> dict[str, Any]:
        command = self._supplier_matching_command(limit_per_part=limit_per_part, quote_keys=None)
        return self._start_task(
            kind="supplier_matching",
            command=command,
            singleton_key="supplier_matching",
            meta={"limit_per_part": limit_per_part},
        )

    # run_supplier_matching_selection es un método que inicia una tarea de coincidencia de proveedores para un conjunto específico de cotizaciones. Acepta una lista de claves de cotización y un parámetro de configuración que especifica el número máximo de coincidencias por parte. El método construye el comando para ejecutar la tarea, verifica si ya hay una tarea activa del mismo tipo (singleton) y, si no la hay, inicia la tarea utilizando el método _start_task y devuelve la información de la tarea iniciada.
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

    # run_agentic_review es un método que inicia una tarea de revisión agentica para procesar cotizaciones. Acepta varios parámetros de configuración, como el número máximo de coincidencias por parte, el modelo a utilizar para la revisión, si se deben deshabilitar los rastros (traces) y una lista opcional de claves de cotización para limitar la revisión a un subconjunto específico. El método construye el comando para ejecutar la tarea, verifica si ya hay una tarea activa del mismo tipo (singleton) y, si no la hay, inicia la tarea utilizando el método _start_task y devuelve la información de la tarea iniciada.
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

    # run_agentic_review_selection es un método que inicia una tarea de revisión agentica para un conjunto específico de cotizaciones. Acepta una lista de claves de cotización y varios parámetros de configuración, como el número máximo de coincidencias por parte, el modelo a utilizar para la revisión y si se deben deshabilitar los rastros (traces). El método construye el comando para ejecutar la tarea, verifica si ya hay una tarea activa del mismo tipo (singleton) y, si no la hay, inicia la tarea utilizando el método _start_task y devuelve la información de la tarea iniciada.
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

    # _supplier_matching_command es un método que construye el comando de línea de comandos para ejecutar una tarea de coincidencia de proveedores. Acepta un parámetro de configuración que especifica el número máximo de coincidencias por parte y una lista opcional de claves de cotización para limitar la coincidencia a un subconjunto específico. El método devuelve una lista de cadenas que representan el comando a ejecutar, incluyendo los argumentos necesarios según si se proporcionan claves de cotización o no.
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

    # _agentic_review_command es un método que construye el comando de línea de comandos para ejecutar una tarea de revisión agentica. Acepta varios parámetros de configuración, como el número máximo de coincidencias por parte, el modelo a utilizar para la revisión, si se deben deshabilitar los rastros (traces) y una lista opcional de claves de cotización para limitar la revisión a un subconjunto específico. El método devuelve una lista de cadenas que representan el comando a ejecutar, incluyendo los argumentos necesarios según los parámetros proporcionados.
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

    # _start_task es un método que inicia una tarea de ejecución dado su tipo, comando, clave de singleton y metadatos. Verifica si ya existe una tarea activa con la misma clave de singleton (si se proporciona) y, si no la hay, crea un nuevo registro de tarea, inicia el proceso asociado al comando, actualiza el estado de la tarea y publica un evento indicando que la tarea ha comenzado. También inicia hilos para manejar la transmisión de salida del proceso y esperar su finalización.
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

    # _stream_output es un método que se ejecuta en un hilo separado para manejar la transmisión de salida de un proceso asociado a una tarea. Lee las líneas de salida del proceso, las escribe en un archivo de log y publica eventos con cada línea de salida para que puedan ser consumidos por otros componentes del sistema (por ejemplo, para mostrar en una interfaz de usuario en tiempo real).
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

    # _wait_for_completion es un método que se ejecuta en un hilo separado para esperar la finalización de un proceso asociado a una tarea. Cuando el proceso termina, actualiza el estado de la tarea con el código de salida, marca la tarea como completada o fallida según el resultado, elimina el proceso de la lista de procesos activos y publica un evento indicando que la tarea ha finalizado.
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

    #  _watch_quotes_loop es un método que se ejecuta en un hilo separado para monitorear continuamente el directorio de cotizaciones en busca de cambios. Mantiene un conjunto de claves de cotización conocidas y una marca de tiempo del último estado cargado. En un bucle infinito, verifica si hay nuevas cotizaciones o cambios en el estado, y si los encuentra, publica eventos correspondientes para notificar a otros componentes del sistema sobre las actualizaciones.
    def _sync_changed_quotes_to_postgres(self, changed_paths: list[Path], reason: str) -> None:
        if API_STORE != "postgres" or not changed_paths:
            return
        database_url = database_url_from_env()
        if not database_url:
            self._event_bus.publish(
                "watcher.error",
                {"message": f"Postgres sync skipped ({reason}): DATABASE_URL is not configured in the backend environment."},
            )
            return
        counters = persist_quote_files(changed_paths, database_url=database_url, dry_run=False)
        if counters.failed:
            raise RuntimeError(
                f"Postgres sync failed after {reason}: imported={counters.imported} updated={counters.updated} failed={counters.failed}"
            )
        self._event_bus.publish(
            "task.log",
            {
                "task_id": "postgres-sync",
                "line": (
                    f"Postgres sync ({reason}): imported={counters.imported} updated={counters.updated} "
                    f"skipped={counters.skipped} files={len(changed_paths)}"
                ),
            },
        )

    def _watch_quotes_loop(self) -> None:
        last_quote_keys = {item["quote_key"] for item in list_quotes()}
        last_state_updated = load_state().get("updated_at")
        while True:
            try:
                quote_paths = sorted(QUOTES_DIR.glob("*.json"))
                current_mtimes = {str(path): path.stat().st_mtime for path in quote_paths}
                changed_paths = [Path(path) for path, mtime in current_mtimes.items() if self._quote_mtimes.get(path) != mtime]
                if changed_paths:
                    self._sync_changed_quotes_to_postgres(changed_paths, reason="quote file update")
                    self._quote_mtimes = current_mtimes

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
                elif changed_paths:
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
