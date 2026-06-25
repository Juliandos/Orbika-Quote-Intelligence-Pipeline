# Agrega comentarios de funcionalidad a todas las funciones
from __future__ import annotations

import json
# Counter es una clase de la biblioteca collections que se utiliza para contar objetos hashables. Es una subclase de dict diseñada para contar elementos de manera eficiente, proporcionando métodos para contar, actualizar y realizar operaciones con los conteos.
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import QUOTES_DIR, STATE_PATH

# load_json es una función que toma una ruta de archivo (Path) como argumento, lee el contenido del archivo, lo decodifica como texto UTF-8 y luego lo convierte de formato JSON a un diccionario de Python utilizando json.loads. Devuelve el diccionario resultante.
def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

# quote_paths es una función que toma un directorio de cotizaciones (quotes_dir) como argumento y devuelve una lista de rutas de archivos (Path) que corresponden a los archivos JSON en ese directorio. Si el directorio no existe, devuelve una lista vacía. Los archivos se ordenan por fecha de modificación en orden descendente (los más recientes primero).
def quote_paths(quotes_dir: Path = QUOTES_DIR) -> list[Path]:
    if not quotes_dir.exists():
        return []
    return sorted(quotes_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)

#   list_quotes es una función que toma un directorio de cotizaciones (quotes_dir) como argumento y devuelve una lista de diccionarios, donde cada diccionario contiene información resumida sobre una cotización. La función recorre los archivos JSON en el directorio, carga su contenido, extrae información relevante (como el estado de carga, el número de repuestos, coincidencias con proveedores, etc.) y la organiza en un formato estructurado para su uso posterior.
def list_quotes(quotes_dir: Path = QUOTES_DIR) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in quote_paths(quotes_dir):
        payload = load_json(path)
        orbika = payload.get("orbika", {})
        matching = payload.get("supplier_matching", {})
        agentic = payload.get("agentic_supplier_matching", {})
        items.append(
            {
                "quote_key": payload.get("quote_key"),
                "path": str(path),
                "generated_at": payload.get("generated_at"),
                "received_at": payload.get("source", {}).get("received_at"),
                "subject": payload.get("source", {}).get("subject"),
                "aviso_id": orbika.get("aviso_id"),
                "placa": orbika.get("placa"),
                "marca": orbika.get("marca"),
                "linea": orbika.get("linea"),
                "load_status": orbika.get("load_status"),
                "repuestos_count": orbika.get("repuestos_count", 0),
                "parts_with_matches": matching.get("summary", {}).get("parts_with_matches", 0),
                "exact_reference_matches": matching.get("summary", {}).get("exact_reference_matches", 0),
                "parts_with_agentic_matches": agentic.get("summary", {}).get(
                    "parts_with_agentic_matches", 0
                ),
            }
        )
    return items

# get_quote_detail es una función que toma una clave de cotización (quote_key) y un directorio de cotizaciones (quotes_dir) como argumentos, construye la ruta al archivo JSON correspondiente a esa clave, verifica si el archivo existe y, si es así, carga su contenido y lo devuelve como un diccionario. Si el archivo no existe, devuelve None.
def get_quote_detail(quote_key: str, quotes_dir: Path = QUOTES_DIR) -> dict[str, Any] | None:
    path = quotes_dir / f"{quote_key}.json"
    if not path.exists():
        return None
    return load_json(path)

# load_state es una función que carga el estado actual de la aplicación desde un archivo JSON ubicado en STATE_PATH. Si el archivo no existe, devuelve un diccionario vacío. Si el archivo existe, lo lee, lo decodifica como JSON y devuelve el contenido como un diccionario de Python.
def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    return load_json(STATE_PATH)

# build_dashboard es una función que construye un resumen del estado actual de las cotizaciones y las actividades relacionadas. Toma un directorio de cotizaciones (quotes_dir) como argumento, recopila información sobre las cotizaciones, como el número total, el estado de carga, los proveedores más activos, etc., y devuelve un diccionario con esta información estructurada para su uso en un panel de control o dashboard.
def build_dashboard(quotes_dir: Path = QUOTES_DIR) -> dict[str, Any]:
    quotes = list_quotes(quotes_dir)
    provider_hits: Counter[str] = Counter()
    load_status: Counter[str] = Counter()
    for item in quotes:
        load_status[str(item.get("load_status") or "unknown")] += 1
        detail = get_quote_detail(str(item["quote_key"]), quotes_dir=quotes_dir)
        for provider_id, count in (
            detail.get("supplier_matching", {}).get("summary", {}).get("provider_hits", {}) if detail else {}
        ).items():
            provider_hits[provider_id] += int(count)

    state = load_state()
    last_run = state.get("last_run", {})
    current = state.get("current", {})
    latest_quote_at = quotes[0]["generated_at"] if quotes else None
    return {
        "counts": {
            "quotes_total": len(quotes),
            "loaded_quotes": load_status.get("loaded", 0),
            "failed_quotes": load_status.get("failed_after_retries", 0),
            "partial_quotes": load_status.get("partial", 0),
        },
        "last_run": last_run,
        "current": current,
        "latest_quote_at": latest_quote_at,
        "provider_hits": dict(provider_hits.most_common()),
        "recent_quotes": quotes[:8],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
