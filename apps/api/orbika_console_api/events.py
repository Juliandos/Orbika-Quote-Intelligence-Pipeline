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

# EventBus es una clase que implementa un sistema de publicación-suscripción para eventos. Permite a los productores publicar eventos y a los consumidores suscribirse para recibir esos eventos en tiempo real. La clase utiliza una cola para cada suscriptor y mantiene un historial de eventos recientes para que los nuevos suscriptores puedan recibir eventos pasados.
class EventBus:
    def __init__(self) -> None:
        # _subscribers es un conjunto que almacena las colas de los suscriptores activos. Cada suscriptor tiene su propia cola para recibir eventos.
        self._subscribers: set[queue.Queue[EventMessage]] = set()
        # _history es una cola de tamaño limitado (deque) que almacena los últimos 500 eventos publicados. Esto permite que los nuevos suscriptores reciban eventos pasados al momento de suscribirse.
        self._history: deque[EventMessage] = deque(maxlen=500)
        # threading.Lock() es un objeto de bloqueo que garantiza que solo un hilo puede acceder a una sección de código a la vez.
        self._lock = threading.Lock()

    # publish es un método que permite a los productores publicar un evento con un nombre y datos asociados. El evento se agrega al historial y se envía a todos los suscriptores activos.
    def publish(self, event: str, data: dict[str, Any]) -> None:
        message = EventMessage(event=event, data=data, timestamp=time.time())
        with self._lock:
            self._history.append(message)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                # que hace put_nowait?, en una cola es intentar agregar un elemento a la cola sin bloquear el hilo. Si la cola está llena, se lanzará una excepción queue.Full en lugar de bloquear el hilo hasta que haya espacio disponible.
                subscriber.put_nowait(message)
            except queue.Full:
                continue

    # subscribe es un método que permite a los consumidores suscribirse para recibir eventos. Crea una nueva cola para el suscriptor, agrega esa cola al conjunto de suscriptores activos y devuelve la cola para que el consumidor pueda leer los eventos. También envía los últimos eventos del historial al nuevo suscriptor.
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
    # unsubscribe es un método que permite a los consumidores cancelar su suscripción. Elimina la cola del suscriptor del conjunto de suscriptores activos, lo que detiene el envío de eventos a esa cola.
    def unsubscribe(self, q: queue.Queue[EventMessage]) -> None:
        with self._lock:
            self._subscribers.discard(q)

# format_sse es una función que formatea un evento y sus datos en el formato de Server-Sent Events (SSE). Toma un nombre de evento y un diccionario de datos, convierte los datos a JSON y devuelve una cadena formateada que puede ser enviada a los clientes que se han suscrito a eventos SSE.
def format_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
