from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class EventMessage:
    event: str
    data: dict[str, Any]
    timestamp: float


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue[EventMessage]] = set()
        self._history: deque[EventMessage] = deque(maxlen=500)
        self._lock = threading.Lock()

    def publish(self, event: str, data: dict[str, Any]) -> None:
        message = EventMessage(event=event, data=data, timestamp=time.time())
        with self._lock:
            self._history.append(message)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(message)
            except queue.Full:
                continue

    def subscribe(self) -> queue.Queue[EventMessage]:
        q: queue.Queue[EventMessage] = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(q)
            history = list(self._history)[-50:]
        for message in history:
            try:
                q.put_nowait(message)
            except queue.Full:
                break
        return q

    def unsubscribe(self, q: queue.Queue[EventMessage]) -> None:
        with self._lock:
            self._subscribers.discard(q)


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
