from __future__ import annotations

import queue
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import API_STORE, FRONTEND_ORIGIN
from .events import EventBus, format_sse
from . import quote_store
from . import postgres_store
from .quote_store import load_state
from .task_runner import TaskManager

app = FastAPI(title="Orbika Console API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

event_bus = EventBus()
task_manager = TaskManager(event_bus)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "store": API_STORE}


def _store():
    if API_STORE == "postgres":
        return postgres_store
    if API_STORE == "json":
        return quote_store
    raise HTTPException(
        status_code=500,
        detail="Invalid ORBIKA_API_STORE. Expected 'json' or 'postgres'.",
    )


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    try:
        return _store().build_dashboard()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/pipeline/state")
def pipeline_state() -> dict[str, Any]:
    return load_state()


@app.get("/api/tasks")
def tasks() -> list[dict[str, Any]]:
    return task_manager.tasks()


@app.post("/api/tasks/incremental-runner/start")
def start_incremental_runner(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return task_manager.start_incremental_runner(
        poll_seconds=int(payload.get("poll_seconds", 300)),
        max_results=int(payload.get("max_results", 50)),
        timeout_ms=int(payload.get("timeout_ms", 45000)),
        max_retries=int(payload.get("max_retries", 4)),
        headed=bool(payload.get("headed", False)),
        gmail_date=payload.get("gmail_date"),
        allow_login_fallback=bool(payload.get("allow_login_fallback", False)),
    )


@app.post("/api/tasks/{task_id}/stop")
def stop_task(task_id: str) -> dict[str, Any]:
    if not task_manager.stop_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found or not running.")
    return {"ok": True}


@app.post("/api/tasks/supplier-matching/run")
def run_supplier_matching(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    quote_keys = [str(item) for item in payload.get("quote_keys", [])]
    if quote_keys:
        return task_manager.run_supplier_matching_selection(
            quote_keys=quote_keys,
            limit_per_part=int(payload.get("limit_per_part", 5)),
        )
    return task_manager.run_supplier_matching(limit_per_part=int(payload.get("limit_per_part", 5)))


@app.post("/api/tasks/agentic-review/run")
def run_agentic_review(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    quote_keys = [str(item) for item in payload.get("quote_keys", [])]
    if quote_keys:
        return task_manager.run_agentic_review_selection(
            quote_keys=quote_keys,
            limit_per_part=int(payload.get("limit_per_part", 5)),
            model=payload.get("model"),
            disable_traces=bool(payload.get("disable_traces", False)),
        )
    return task_manager.run_agentic_review(
        limit_per_part=int(payload.get("limit_per_part", 5)),
        model=payload.get("model"),
        disable_traces=bool(payload.get("disable_traces", False)),
    )


@app.get("/api/quotes")
def quotes() -> list[dict[str, Any]]:
    try:
        return _store().list_quotes()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/quotes/{quote_key}")
def quote_detail(quote_key: str) -> dict[str, Any]:
    try:
        payload = _store().get_quote_detail(quote_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Quote not found.")
    return payload


@app.get("/api/events")
def events() -> StreamingResponse:
    subscriber = event_bus.subscribe()

    def event_stream():
        try:
            yield format_sse("connected", {"ok": True, "connected_at": time.time()})
            while True:
                try:
                    message = subscriber.get(timeout=10)
                    yield format_sse(message.event, {"timestamp": message.timestamp, **message.data})
                except queue.Empty:
                    yield format_sse("heartbeat", {"ts": time.time()})
        finally:
            event_bus.unsubscribe(subscriber)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
