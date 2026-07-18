"""Graph-oriented read helpers for the Orbika API."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL


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


def _database_url() -> str | None:
    if not DATABASE_URL:
        return None
    return DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)


def _connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


def load_quote_graph_context(quote_key: str) -> dict[str, Any] | None:
    """Load the logical graph context for one quote from PostgreSQL."""

    resolved_url = _database_url()
    if not resolved_url:
        return None

    try:
        with _connect(resolved_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH quote_node_keys AS (
                  SELECT node_key
                  FROM graph_nodes
                  WHERE quote_key = %s
                  UNION
                  SELECT source_node_key AS node_key
                  FROM graph_edges
                  WHERE quote_key = %s
                  UNION
                  SELECT target_node_key AS node_key
                  FROM graph_edges
                  WHERE quote_key = %s
                )
                SELECT gn.*
                FROM graph_nodes gn
                WHERE gn.node_key IN (SELECT node_key FROM quote_node_keys)
                ORDER BY gn.node_type, gn.label, gn.node_key
                """,
                (quote_key, quote_key, quote_key),
            )
            nodes = cur.fetchall()

            cur.execute(
                """
                SELECT *
                FROM graph_edges
                WHERE quote_key = %s
                ORDER BY created_at, edge_type, edge_key
                """,
                (quote_key,),
            )
            edges = cur.fetchall()
    except Exception:
        return None

    if not nodes and not edges:
        return None

    node_types = Counter(str(node.get("node_type") or "unknown") for node in nodes)
    edge_types = Counter(str(edge.get("edge_type") or "unknown") for edge in edges)

    return {
        "quote_key": quote_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": dict(node_types.most_common()),
            "edge_types": dict(edge_types.most_common()),
        },
        "nodes": [_jsonable(node) for node in nodes],
        "edges": [_jsonable(edge) for edge in edges],
    }
