"""Graph-oriented read helpers over PostgreSQL.

This module exposes a logical graph projection built on top of the existing
relational quote and provider tables. The graph is read-only and acts as a
traceable navigation layer for match evidence and operator review.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from tools.postgres_quote_persistence import database_url_from_env


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


def _connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


def load_quote_graph_context(
    quote_key: str,
    *,
    database_url: str | None = None,
) -> dict[str, Any] | None:
    """Load the logical graph context for one quote from PostgreSQL.

    The function is intentionally read-only and defensive. If the database or
    the graph views are unavailable, it returns ``None`` rather than breaking
    operational flows.
    """

    resolved_url = database_url or database_url_from_env()
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
