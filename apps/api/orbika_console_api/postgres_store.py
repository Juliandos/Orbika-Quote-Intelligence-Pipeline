# Agrega comentarios de funcionalidad a todas las funciones
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL
from .quote_store import load_state

# _database_url es una funciÃ³n que verifica si la variable de entorno DATABASE_URL estÃ¡ configurada. Si no lo estÃ¡, lanza una excepciÃ³n RuntimeError indicando que DATABASE_URL es necesario cuando ORBIKA_API_STORE estÃ¡ configurado como 'postgres'. Si DATABASE_URL estÃ¡ configurado, reemplaza el prefijo "postgresql+psycopg://" con "postgresql://" para asegurar la compatibilidad con psycopg y devuelve la URL de conexiÃ³n resultante.
def _database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required when ORBIKA_API_STORE=postgres.")
    return DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)

# _connect es una funciÃ³n que establece una conexiÃ³n a la base de datos PostgreSQL utilizando psycopg. Utiliza la URL de conexiÃ³n proporcionada por _database_url() y configura el row_factory para que las filas devueltas por las consultas sean diccionarios en lugar de tuplas, lo que facilita el acceso a los datos por nombre de columna.
def _connect() -> psycopg.Connection:
    return psycopg.connect(_database_url(), row_factory=dict_row)

# EventBus es una clase que implementa un sistema de publicaciÃ³n-suscripciÃ³n para eventos. Permite a los productores publicar eventos y a los consumidores suscribirse para recibir esos eventos en tiempo real. La clase utiliza una cola para cada suscriptor y mantiene un historial de eventos recientes para que los nuevos suscriptores puedan recibir eventos pasados.
def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value

# _quote_summary es una funciÃ³n que toma una fila de datos (row) como argumento y extrae informaciÃ³n relevante para crear un resumen de una cotizaciÃ³n. La funciÃ³n devuelve un diccionario con campos especÃ­ficos como quote_key, generated_at, received_at, subject, aviso_id, placa, marca, linea, load_status, repuestos_count, parts_with_matches, exact_reference_matches y parts_with_agentic_matches. Esta funciÃ³n se utiliza para transformar los datos crudos de la base de datos en un formato estructurado y fÃ¡cil de usar para el frontend o para otros propÃ³sitos.
def _quote_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "quote_key": row["quote_key"],
        "path": row.get("source_file_path") or "",
        "generated_at": _jsonable(row.get("processed_at") or row.get("updated_at")),
        "received_at": _jsonable(row.get("received_at")),
        "subject": row.get("source_subject"),
        "aviso_id": row.get("aviso_id"),
        "placa": row.get("plate"),
        "marca": row.get("brand"),
        "linea": row.get("line"),
        "load_status": row.get("load_status"),
        "repuestos_count": int(row.get("parts_total") or 0),
        "parts_with_matches": int(row.get("parts_with_matches") or 0),
        "exact_reference_matches": int(row.get("exact_reference_matches") or 0),
        "parts_with_agentic_matches": int(row.get("parts_with_agentic_matches") or 0),
    }

# list_quotes es una funciÃ³n que se conecta a la base de datos PostgreSQL, ejecuta una consulta SQL para obtener un resumen de las cotizaciones almacenadas en la base de datos, y devuelve una lista de diccionarios con la informaciÃ³n resumida de cada cotizaciÃ³n. La funciÃ³n utiliza _quote_summary para transformar cada fila de resultados en un formato estructurado y fÃ¡cil de usar.
def list_quotes() -> list[dict[str, Any]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              q.quote_key,
              q.source_file_path,
              q.processed_at,
              q.updated_at,
              q.received_at,
              q.source_subject,
              q.aviso_id,
              q.load_status,
              v.plate,
              v.brand,
              v.line,
              COUNT(DISTINCT p.id)::int AS parts_total,
              COUNT(DISTINCT sm.part_id)::int AS parts_with_matches,
              COUNT(sm.id) FILTER (WHERE sm.match_type = 'exact_reference')::int
                AS exact_reference_matches,
              COUNT(DISTINCT ar.part_id)::int AS parts_with_agentic_matches
            FROM quotes q
            LEFT JOIN vehicles v ON v.quote_id = q.id
            LEFT JOIN parts p ON p.quote_id = q.id
            LEFT JOIN supplier_matches sm ON sm.part_id = p.id
            LEFT JOIN agentic_reviews ar ON ar.part_id = p.id
            GROUP BY q.id, v.id
            ORDER BY COALESCE(q.received_at, q.processed_at, q.updated_at) DESC
            """
        )
        return [_quote_summary(row) for row in cur.fetchall()]

# get_quote_detail es una funciÃ³n que se conecta a la base de datos PostgreSQL, ejecuta una consulta SQL para obtener los detalles de una cotizaciÃ³n especÃ­fica identificada por quote_key, y devuelve un diccionario con toda la informaciÃ³n detallada de esa cotizaciÃ³n. La funciÃ³n tambiÃ©n obtiene informaciÃ³n relacionada como partes, coincidencias con proveedores y revisiones agentic, y organiza todos estos datos en un formato estructurado para su uso en el frontend o para otros propÃ³sitos. Si no se encuentra la cotizaciÃ³n, devuelve None.
def build_dashboard() -> dict[str, Any]:
    quotes = list_quotes()
    provider_hits: Counter[str] = Counter()
    load_status: Counter[str] = Counter()

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT provider_id, COUNT(*)::int AS hits
            FROM supplier_matches
            GROUP BY provider_id
            ORDER BY hits DESC
            """
        )
        provider_hits.update({row["provider_id"]: row["hits"] for row in cur.fetchall()})

    for item in quotes:
        load_status[str(item.get("load_status") or "unknown")] += 1

    state = load_state()
    return {
        "counts": {
            "quotes_total": len(quotes),
            "loaded_quotes": load_status.get("loaded", 0),
            "failed_quotes": load_status.get("failed_after_retries", 0) + load_status.get("failed", 0),
            "partial_quotes": load_status.get("partial", 0),
        },
        "last_run": state.get("last_run", {}),
        "current": state.get("current", {}),
        "latest_quote_at": quotes[0]["generated_at"] if quotes else None,
        "provider_hits": dict(provider_hits.most_common()),
        "recent_quotes": quotes[:8],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

# get_quote_detail es una funciÃ³n que se conecta a la base de datos PostgreSQL, ejecuta una consulta SQL para obtener los detalles de una cotizaciÃ³n especÃ­fica identificada por quote_key, y devuelve un diccionario con toda la informaciÃ³n detallada de esa cotizaciÃ³n. La funciÃ³n tambiÃ©n obtiene informaciÃ³n relacionada como partes, coincidencias con proveedores y revisiones agentic, y organiza todos estos datos en un formato estructurado para su uso en el frontend o para otros propÃ³sitos. Si no se encuentra la cotizaciÃ³n, devuelve None.
def get_quote_detail(quote_key: str) -> dict[str, Any] | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              q.*,
              e.gmail_id,
              e.message_id,
              e.thread_id,
              e.sender,
              e.subject AS email_subject,
              e.raw_excerpt,
              v.plate,
              v.brand,
              v.line,
              v.version,
              v.model_year,
              v.vin,
              v.color,
              w.commercial_name,
              w.delivery_workshop,
              w.city,
              w.address,
              w.phone
            FROM quotes q
            LEFT JOIN emails e ON e.id = q.email_id
            LEFT JOIN vehicles v ON v.quote_id = q.id
            LEFT JOIN workshops w ON w.quote_id = q.id
            WHERE q.quote_key = %s
            """,
            (quote_key,),
        )
        quote = cur.fetchone()
        if quote is None:
            return None

        cur.execute(
            """
            SELECT *
            FROM parts
            WHERE quote_id = %s
            ORDER BY position
            """,
            (quote["id"],),
        )
        parts = cur.fetchall()
        part_ids = [part["id"] for part in parts]

        matches_by_part: dict[Any, list[dict[str, Any]]] = {part_id: [] for part_id in part_ids}
        reviews_by_part: dict[Any, dict[str, Any]] = {}
        if part_ids:
            cur.execute(
                """
                SELECT *
                FROM supplier_matches
                WHERE part_id = ANY(%s)
                ORDER BY part_id, rank NULLS LAST, score_percent DESC
                """,
                (part_ids,),
            )
            for match in cur.fetchall():
                matches_by_part.setdefault(match["part_id"], []).append(match)

            cur.execute(
                """
                SELECT *
                FROM agentic_reviews
                WHERE part_id = ANY(%s)
                ORDER BY created_at DESC
                """,
                (part_ids,),
            )
            for review in cur.fetchall():
                reviews_by_part.setdefault(review["part_id"], review)

    orbika_parts = []
    supplier_parts = []
    agentic_parts = []
    provider_hits: Counter[str] = Counter()
    exact_reference_matches = 0

    for part in parts:
        raw_part = dict(part.get("raw_payload") or {})
        raw_part.setdefault("name", part["name"])
        raw_part.setdefault("quantity", _jsonable(part.get("quantity")))
        raw_part.setdefault("raw_status", part.get("raw_status"))
        orbika_parts.append(_jsonable(raw_part))

        matches = [_match_payload(match) for match in matches_by_part.get(part["id"], [])]
        for match in matches:
            provider_id = match.get("provider_id")
            if provider_id:
                provider_hits[provider_id] += 1
            if match.get("match_type") == "exact_reference":
                exact_reference_matches += 1

        supplier_parts.append(
            {
                "part_name": part["name"],
                "requested_reference": part.get("requested_reference"),
                "best_score_percent": matches[0].get("score_percent") if matches else 0,
                "best_provider_id": matches[0].get("provider_id") if matches else None,
                "matches": matches,
            }
        )

        review = reviews_by_part.get(part["id"])
        selected_options = _jsonable(review.get("selected_options") if review else []) or []
        agentic_parts.append(
            {
                "part_name": part["name"],
                "top_provider_id": selected_options[0].get("provider_id") if selected_options else None,
                "top_score_percent": review.get("confidence_percent") if review else 0,
                "review_status": review.get("status") if review else None,
                "reviewer_mode": review.get("reviewer_mode") if review else None,
                "summary_comment": review.get("summary_comment") if review else None,
                "risk_notes": _jsonable(review.get("risk_notes") if review else []),
                "preference_notes": _jsonable(review.get("preference_notes") if review else []),
                "selected_matches": selected_options,
            }
        )

    parts_total = len(parts)
    parts_with_matches = sum(1 for item in supplier_parts if item["matches"])
    parts_with_agentic_matches = sum(1 for item in agentic_parts if item["selected_matches"])

    payload = {
        "quote_key": quote["quote_key"],
        "generated_at": _jsonable(quote.get("processed_at") or quote.get("updated_at")),
        "quote_url_masked": quote.get("quote_url_masked"),
        "source": {
            "gmail_id": quote.get("gmail_id"),
            "message_id": quote.get("message_id"),
            "thread_id": quote.get("thread_id"),
            "sender": quote.get("sender"),
            "subject": quote.get("source_subject") or quote.get("email_subject"),
            "received_at": _jsonable(quote.get("received_at")),
            "raw_excerpt": quote.get("raw_excerpt"),
        },
        "orbika": {
            "aviso_id": quote.get("aviso_id"),
            "load_status": quote.get("load_status"),
            "warnings": _jsonable(quote.get("warnings") or []),
            "placa": quote.get("plate"),
            "marca": quote.get("brand"),
            "linea": quote.get("line"),
            "version": quote.get("version"),
            "ano": quote.get("model_year"),
            "vin": quote.get("vin"),
            "color": quote.get("color"),
            "nombre_comercial": quote.get("commercial_name"),
            "taller_entrega": quote.get("delivery_workshop"),
            "ciudad": quote.get("city"),
            "direccion": quote.get("address"),
            "telefono": quote.get("phone"),
            "repuestos_count": parts_total,
            "parts": orbika_parts,
        },
        "supplier_matching": {
            "summary": {
                "parts_total": parts_total,
                "parts_with_matches": parts_with_matches,
                "exact_reference_matches": exact_reference_matches,
                "provider_hits": dict(provider_hits.most_common()),
            },
            "parts": supplier_parts,
        },
        "agentic_supplier_matching": {
            "summary": {
                "parts_total": parts_total,
                "parts_with_agentic_matches": parts_with_agentic_matches,
            },
            "parts": agentic_parts,
        },
    }
    return _jsonable(payload)

# _match_payload es una funciÃ³n que toma un diccionario de coincidencia (match) como argumento y extrae informaciÃ³n relevante para crear un resumen de esa coincidencia. La funciÃ³n devuelve un diccionario con campos especÃ­ficos como provider_id, provider_name, product_name, reference, sku, brand, category_name, subcategory_name, detail_url, price, currency, availability, match_type, score_percent, rank, reasons y risk_flags. Esta funciÃ³n se utiliza para transformar los datos crudos de la base de datos en un formato estructurado y fÃ¡cil de usar para el frontend o para otros propÃ³sitos.
def _match_payload(match: dict[str, Any]) -> dict[str, Any]:
    raw = dict(match.get("raw_payload") or {})
    raw.update(
        {
            "provider_id": match.get("provider_id"),
            "provider_name": match.get("provider_name"),
            "product_name": match.get("product_name"),
            "reference": match.get("reference"),
            "sku": match.get("sku"),
            "brand": match.get("brand"),
            "category_name": match.get("category_name"),
            "subcategory_name": match.get("subcategory_name"),
            "detail_url": match.get("detail_url"),
            "price": _jsonable(match.get("price")),
            "currency": match.get("currency"),
            "availability": match.get("availability"),
            "match_type": match.get("match_type"),
            "score_percent": match.get("score_percent"),
            "rank": match.get("rank"),
            "reasons": _jsonable(match.get("reasons") or []),
            "risk_flags": _jsonable(match.get("risk_flags") or []),
            "compatibility_warnings": _jsonable(match.get("compatibility_warnings") or []),
            "preference_notes": _jsonable(match.get("preference_notes") or []),
            "compatibility_state": match.get("compatibility_state"),
            "compatibility_summary": match.get("compatibility_summary"),
            "operational_note": match.get("operational_note"),
        }
    )
    return _jsonable(raw)
