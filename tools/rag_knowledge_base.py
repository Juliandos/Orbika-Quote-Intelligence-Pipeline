#!/usr/bin/env python3
"""Technical RAG ingestion and retrieval for Orbika part selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None


DEFAULT_SOURCE_DIR = Path("knowledge/rag_sources")
DEFAULT_MAX_CHARS = 1400
DEFAULT_OVERLAP = 180
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_EMBED_BATCH_SIZE = 24
DEFAULT_VECTOR_CANDIDATE_LIMIT = 8
DEFAULT_TEXT_CANDIDATE_LIMIT = 8
DEFAULT_EMBEDDING_PROVIDER = "local"
DEFAULT_LOCAL_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_MODEL = DEFAULT_LOCAL_EMBEDDING_MODEL
DEFAULT_EMBEDDING_DIMENSIONS = 384
DEFAULT_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

YEAR_RANGE_PATTERN = re.compile(r"(?<!\d)(20\d{2})\s*[-/]\s*(20\d{2})(?!\d)")
YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


class DryRunRollback(Exception):
    """Signal used to rollback a successful dry-run transaction."""


@dataclass
class IngestCounters:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    chunks: int = 0
    embedded_chunks: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if len(self.warnings) < 50:
            self.warnings.append(message)


@dataclass
class EmbeddingConfig:
    provider: str
    model: str
    dimensions: int
    api_key: str = ""
    base_url: str = DEFAULT_OPENAI_EMBEDDINGS_URL


def database_url_from_env() -> str | None:
    value = os.environ.get("DATABASE_URL")
    if not value:
        return None
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value if value is not None else {})


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def bool_from_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def int_from_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def unique_tokens(*values: Any) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for value in values:
        for token in re.findall(r"[a-z0-9]+", normalize_text(value)):
            if len(token) < 3:
                continue
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens


def source_files(source_dir: Path, limit: int | None = None) -> list[Path]:
    files = [
        path
        for path in sorted(source_dir.glob("*.pdf"))
        if path.is_file() and not path.name.endswith(":Zone.Identifier")
    ]
    if limit is not None:
        files = files[:limit]
    return files


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf_pages(path: Path) -> tuple[dict[str, Any], list[tuple[int, str]]]:
    if PdfReader is None:
        raise RuntimeError(
            "pypdf is required for PDF ingestion. Run with: uv run --with pypdf python tools/rag_knowledge_base.py ingest ..."
        )
    reader = PdfReader(str(path))
    metadata = reader.metadata or {}
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        if cleaned:
            pages.append((index, cleaned))
    info = {
        "title": str(getattr(metadata, "title", "") or path.stem).strip() or path.stem,
        "author": str(getattr(metadata, "author", "") or "").strip() or None,
        "producer": str(getattr(metadata, "producer", "") or "").strip() or None,
        "creator": str(getattr(metadata, "creator", "") or "").strip() or None,
        "page_count": len(reader.pages),
    }
    return info, pages


def chunk_page_text(
    page_number: int,
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    if not text:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    text = re.sub(r"\s+", " ", text).strip()
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split = text.rfind(" ", start, end)
            if split > start + int(max_chars * 0.65):
                end = split
        snippet = text[start:end].strip()
        if snippet:
            chunks.append(
                {
                    "page_start": page_number,
                    "page_end": page_number,
                    "content": snippet,
                    "content_normalized": normalize_text(snippet),
                    "metadata": {"page": page_number},
                }
            )
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def build_chunks(
    pages: list[tuple[int, str]],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page_number, text in pages:
        chunks.extend(
            chunk_page_text(
                page_number,
                text,
                max_chars=max_chars,
                overlap=overlap,
            )
        )
    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index
    return chunks


def embedding_config_from_env() -> EmbeddingConfig | None:
    provider = (os.environ.get("RAG_EMBEDDING_PROVIDER") or DEFAULT_EMBEDDING_PROVIDER).strip().lower()
    model = (os.environ.get("RAG_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()
    dimensions = int_from_env("RAG_EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS)
    if provider == "local":
        return EmbeddingConfig(provider=provider, model=model, dimensions=dimensions)
    if provider == "openai":
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return None
        base_url = (os.environ.get("RAG_EMBEDDING_BASE_URL") or DEFAULT_OPENAI_EMBEDDINGS_URL).strip()
        return EmbeddingConfig(
            provider=provider,
            model=model or DEFAULT_OPENAI_EMBEDDING_MODEL,
            dimensions=dimensions,
            api_key=api_key,
            base_url=base_url,
        )
    return None


def vector_search_enabled() -> bool:
    return bool_from_env("RAG_VECTOR_SEARCH_ENABLED", True)


def vector_literal(values: list[float] | tuple[float, ...] | None) -> str | None:
    if not values:
        return None
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


@lru_cache(maxsize=4)
def load_local_embedding_model(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Local embeddings require sentence-transformers. "
            "Run with: uv run --with sentence-transformers --with torch --with pypdf python tools/rag_knowledge_base.py ..."
        ) from exc
    return SentenceTransformer(model_name)


def batched(values: list[str], batch_size: int) -> list[list[str]]:
    return [values[index : index + batch_size] for index in range(0, len(values), batch_size)]


def fetch_openai_embeddings(texts: list[str], config: EmbeddingConfig) -> list[list[float]]:
    if not texts:
        return []
    payload: dict[str, Any] = {
        "model": config.model,
        "input": texts,
    }
    if config.dimensions and config.model.startswith("text-embedding-3"):
        payload["dimensions"] = config.dimensions
    request = urlrequest.Request(
        config.base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:  # pragma: no cover - network dependency
        details = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"embedding request failed: {exc.code} {details}") from exc
    except urlerror.URLError as exc:  # pragma: no cover - network dependency
        raise RuntimeError(f"embedding request failed: {exc}") from exc

    raw_items = data.get("data") or []
    items = sorted(raw_items, key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") or [] for item in items]
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedding response size mismatch: expected {len(texts)} items, got {len(vectors)}"
        )
    return vectors


def fetch_local_embeddings(
    texts: list[str],
    config: EmbeddingConfig,
    *,
    kind: str = "document",
) -> list[list[float]]:
    if not texts:
        return []
    model = load_local_embedding_model(config.model)
    if "e5" in config.model.lower():
        prefix = "query: " if kind == "query" else "passage: "
        prepared_texts = [f"{prefix}{text}".strip() for text in texts]
    else:
        prepared_texts = [str(text).strip() for text in texts]
    vectors = model.encode(
        prepared_texts,
        batch_size=max(1, int_from_env("RAG_LOCAL_EMBED_BATCH_SIZE", DEFAULT_EMBED_BATCH_SIZE)),
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedding response size mismatch: expected {len(texts)} items, got {len(vectors)}"
        )
    embedding_vectors = [vector.tolist() for vector in vectors]
    if embedding_vectors and len(embedding_vectors[0]) != config.dimensions:
        raise RuntimeError(
            f"embedding dimension mismatch: expected {config.dimensions}, got {len(embedding_vectors[0])}"
        )
    return embedding_vectors


def fetch_embeddings(
    texts: list[str],
    config: EmbeddingConfig,
    *,
    kind: str = "document",
) -> list[list[float]]:
    if config.provider == "local":
        return fetch_local_embeddings(texts, config, kind=kind)
    if config.provider == "openai":
        return fetch_openai_embeddings(texts, config)
    raise RuntimeError(f"Unsupported embedding provider: {config.provider}")


def attach_embeddings_to_chunks(
    chunks: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    skip_embeddings: bool = False,
) -> tuple[int, list[str]]:
    if skip_embeddings or dry_run:
        return 0, []
    if not vector_search_enabled():
        return 0, []
    config = embedding_config_from_env()
    if config is None:
        return 0, ["Embeddings skipped: RAG embedding configuration missing."]

    texts = [str(chunk.get("content") or "") for chunk in chunks]
    if not any(texts):
        return 0, []

    embedded_count = 0
    warnings: list[str] = []
    batch_size = max(1, int_from_env("RAG_EMBED_BATCH_SIZE", DEFAULT_EMBED_BATCH_SIZE))

    try:
        cursor = 0
        for batch in batched(texts, batch_size):
            vectors = fetch_embeddings(batch, config, kind="document")
            for offset, vector in enumerate(vectors):
                chunk = chunks[cursor + offset]
                chunk["embedding"] = vector
                chunk["embedding_model"] = config.model
                chunk["embedding_dimensions"] = config.dimensions
                chunk["embedded_at"] = datetime.now(timezone.utc)
                embedded_count += 1
            cursor += len(batch)
    except Exception as exc:
        for chunk in chunks:
            chunk.pop("embedding", None)
            chunk.pop("embedding_model", None)
            chunk.pop("embedding_dimensions", None)
            chunk.pop("embedded_at", None)
        warnings.append(f"Embeddings skipped after request failure: {exc}")
        return 0, warnings

    return embedded_count, warnings


def upsert_document(
    cur: "psycopg.Cursor",
    *,
    path: Path,
    sha256: str,
    info: dict[str, Any],
) -> tuple[str, bool]:
    cur.execute("SELECT id FROM rag_documents WHERE sha256 = %s", (sha256,))
    existing = cur.fetchone()
    payload = {
        "pdf_metadata": {
            "author": info.get("author"),
            "producer": info.get("producer"),
            "creator": info.get("creator"),
        }
    }
    if existing:
        cur.execute(
            """
            UPDATE rag_documents
            SET title = %s,
                source_type = 'pdf',
                file_path = %s,
                language = %s,
                status = 'active',
                page_count = %s,
                metadata = %s
            WHERE id = %s
            """,
            (
                info.get("title") or path.stem,
                str(path),
                "es",
                int(info.get("page_count") or 0),
                jsonb(payload),
                existing["id"],
            ),
        )
        return existing["id"], True

    cur.execute(
        """
        INSERT INTO rag_documents (
          title, source_type, file_path, sha256, language, status, page_count, metadata
        )
        VALUES (%s, 'pdf', %s, %s, %s, 'active', %s, %s)
        RETURNING id
        """,
        (
            info.get("title") or path.stem,
            str(path),
            sha256,
            "es",
            int(info.get("page_count") or 0),
            jsonb(payload),
        ),
    )
    return cur.fetchone()["id"], False


def replace_chunks(
    cur: "psycopg.Cursor",
    *,
    document_id: str,
    chunks: list[dict[str, Any]],
) -> int:
    cur.execute("DELETE FROM rag_chunks WHERE document_id = %s", (document_id,))
    for chunk in chunks:
        embedding = vector_literal(chunk.get("embedding"))
        cur.execute(
            """
            INSERT INTO rag_chunks (
              document_id, chunk_index, page_start, page_end,
              content, content_normalized, metadata,
              embedding, embedding_model, embedding_dimensions, embedded_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
            """,
            (
                document_id,
                chunk["chunk_index"],
                chunk.get("page_start"),
                chunk.get("page_end"),
                chunk["content"],
                chunk["content_normalized"],
                jsonb(chunk.get("metadata") or {}),
                embedding,
                chunk.get("embedding_model"),
                chunk.get("embedding_dimensions"),
                chunk.get("embedded_at"),
            ),
        )
    return len(chunks)


def ingest_documents(
    files: list[Path],
    *,
    database_url: str,
    dry_run: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
    skip_embeddings: bool = False,
) -> IngestCounters:
    counters = IngestCounters()
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        try:
            with conn.cursor() as cur:
                for path in files:
                    try:
                        sha256 = sha256_file(path)
                        info, pages = extract_pdf_pages(path)
                        if not pages:
                            counters.skipped += 1
                            counters.warn(f"{path.name}: no extractable text found")
                            continue
                        document_id, existed = upsert_document(
                            cur,
                            path=path,
                            sha256=sha256,
                            info=info,
                        )
                        chunks = build_chunks(pages, max_chars=max_chars, overlap=overlap)
                        embedded_count, embedding_warnings = attach_embeddings_to_chunks(
                            chunks,
                            dry_run=dry_run,
                            skip_embeddings=skip_embeddings,
                        )
                        for warning in embedding_warnings:
                            counters.warn(f"{path.name}: {warning}")
                        counters.embedded_chunks += embedded_count
                        chunk_count = replace_chunks(
                            cur,
                            document_id=document_id,
                            chunks=chunks,
                        )
                        counters.chunks += chunk_count
                        if existed:
                            counters.updated += 1
                        else:
                            counters.imported += 1
                    except Exception as exc:
                        counters.failed += 1
                        counters.warn(f"{path.name}: {exc}")
                if dry_run:
                    raise DryRunRollback()
                conn.commit()
        except DryRunRollback:
            conn.rollback()
    return counters


def format_page_span(page_start: Any, page_end: Any) -> str:
    if not page_start:
        return "n/a"
    if page_end and page_end != page_start:
        return f"{page_start}-{page_end}"
    return str(page_start)


def text_search_chunks(
    *,
    database_url: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        return []
    sql = """
        SELECT
          d.id AS document_id,
          d.title,
          d.file_path,
          c.id AS chunk_id,
          c.chunk_index,
          c.page_start,
          c.page_end,
          c.content,
          ts_rank_cd(
            to_tsvector('simple', c.content_normalized),
            websearch_to_tsquery('simple', %s)
          ) AS score
        FROM rag_chunks c
        JOIN rag_documents d ON d.id = c.document_id
        WHERE d.status = 'active'
          AND to_tsvector('simple', c.content_normalized)
              @@ websearch_to_tsquery('simple', %s)
        ORDER BY score DESC, d.title, c.page_start, c.chunk_index
        LIMIT %s
    """
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, (normalized_query, normalized_query, limit))
        return [dict(row) for row in cur.fetchall()]


def vector_search_chunks(
    *,
    database_url: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not vector_search_enabled():
        return []
    config = embedding_config_from_env()
    if config is None:
        return []
    vectors = fetch_embeddings([query], config, kind="query")
    if not vectors:
        return []
    vector = vector_literal(vectors[0])
    sql = """
        SELECT
          d.id AS document_id,
          d.title,
          d.file_path,
          c.id AS chunk_id,
          c.chunk_index,
          c.page_start,
          c.page_end,
          c.content,
          (1 - (c.embedding <=> %s::vector)) AS score
        FROM rag_chunks c
        JOIN rag_documents d ON d.id = c.document_id
        WHERE d.status = 'active'
          AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %s::vector ASC, d.title, c.page_start, c.chunk_index
        LIMIT %s
    """
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, (vector, vector, limit))
        return [dict(row) for row in cur.fetchall()]


def merge_search_hits(
    text_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    max_text_score = max((max(float(hit.get("score") or 0.0), 0.0) for hit in text_hits), default=0.0)
    max_vector_score = max((max(float(hit.get("score") or 0.0), 0.0) for hit in vector_hits), default=0.0)

    for hit in text_hits:
        key = (str(hit.get("document_id")), str(hit.get("chunk_id")))
        row = dict(hit)
        row["text_score"] = max(float(hit.get("score") or 0.0), 0.0)
        row["vector_score"] = 0.0
        row["retrieval_mode"] = "text"
        merged[key] = row

    for hit in vector_hits:
        key = (str(hit.get("document_id")), str(hit.get("chunk_id")))
        row = merged.get(key)
        vector_score = max(float(hit.get("score") or 0.0), 0.0)
        if row is None:
            row = dict(hit)
            row["text_score"] = 0.0
            row["vector_score"] = vector_score
            row["retrieval_mode"] = "vector"
            merged[key] = row
            continue
        row["vector_score"] = vector_score
        row["retrieval_mode"] = "hybrid"

    ranked: list[dict[str, Any]] = []
    for row in merged.values():
        text_score = float(row.get("text_score") or 0.0)
        vector_score = float(row.get("vector_score") or 0.0)
        text_component = text_score / max_text_score if max_text_score > 0 else 0.0
        vector_component = vector_score / max_vector_score if max_vector_score > 0 else 0.0
        combined = (text_component * 0.45) + (vector_component * 0.55)
        if text_component > 0 and vector_component > 0:
            combined += 0.05
        row["score"] = round(combined, 6)
        ranked.append(row)

    ranked.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            float(row.get("vector_score") or 0.0),
            float(row.get("text_score") or 0.0),
            str(row.get("title") or ""),
            int(row.get("page_start") or 0),
            int(row.get("chunk_index") or 0),
        ),
        reverse=True,
    )
    return ranked[:limit]


def search_chunks(
    *,
    database_url: str,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    mode: str = "auto",
) -> list[dict[str, Any]]:
    mode = (mode or "auto").strip().lower()
    text_limit = max(limit * 2, DEFAULT_TEXT_CANDIDATE_LIMIT)
    vector_limit = max(limit * 2, DEFAULT_VECTOR_CANDIDATE_LIMIT)

    if mode == "text":
        results = text_search_chunks(database_url=database_url, query=query, limit=text_limit)
        for row in results:
            row["retrieval_mode"] = "text"
            row["text_score"] = float(row.get("score") or 0.0)
            row["vector_score"] = 0.0
        return results[:limit]

    if mode == "vector":
        results = vector_search_chunks(database_url=database_url, query=query, limit=vector_limit)
        for row in results:
            row["retrieval_mode"] = "vector"
            row["text_score"] = 0.0
            row["vector_score"] = float(row.get("score") or 0.0)
        return results[:limit]

    text_hits = text_search_chunks(database_url=database_url, query=query, limit=text_limit)
    vector_hits: list[dict[str, Any]] = []
    if mode in {"auto", "hybrid"}:
        try:
            vector_hits = vector_search_chunks(database_url=database_url, query=query, limit=vector_limit)
        except Exception:
            vector_hits = []

    if mode == "hybrid":
        return merge_search_hits(text_hits, vector_hits, limit=limit)
    if vector_hits:
        return merge_search_hits(text_hits, vector_hits, limit=limit)

    for row in text_hits:
        row["retrieval_mode"] = "text"
        row["text_score"] = float(row.get("score") or 0.0)
        row["vector_score"] = 0.0
    return text_hits[:limit]


def years_covered(text: str) -> set[int]:
    found: set[int] = set()
    for start, end in YEAR_RANGE_PATTERN.findall(text):
        for year in range(int(start), int(end) + 1):
            found.add(year)
    for year in YEAR_PATTERN.findall(text):
        found.add(int(year))
    return found


def build_candidate_query(
    *,
    quote_context: dict[str, Any],
    part: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    vehicle = quote_context.get("vehicle") or quote_context.get("orbika") or quote_context
    tokens = unique_tokens(
        part.get("part_name"),
        part.get("requested_reference"),
        vehicle.get("marca"),
        vehicle.get("linea"),
        vehicle.get("version"),
        vehicle.get("ano"),
        candidate.get("product_name"),
        candidate.get("reference"),
        candidate.get("sku"),
        candidate.get("brand"),
        candidate.get("category_name"),
        candidate.get("subcategory_name"),
    )
    return " ".join(tokens[:18])


def retrieve_candidate_evidence(
    *,
    quote_context: dict[str, Any],
    part: dict[str, Any],
    candidate: dict[str, Any],
    database_url: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    database_url = database_url or database_url_from_env()
    if not database_url:
        return {"verdict": "no_evidence", "summary": None, "citations": []}

    query = build_candidate_query(
        quote_context=quote_context,
        part=part,
        candidate=candidate,
    )
    if not query:
        return {"verdict": "no_evidence", "summary": None, "citations": []}

    hits = search_chunks(database_url=database_url, query=query, limit=limit, mode="auto")
    if not hits:
        return {"verdict": "no_evidence", "summary": None, "citations": []}

    requested_ref = normalize_text(part.get("requested_reference"))
    candidate_ref = normalize_text(candidate.get("reference") or candidate.get("sku"))
    candidate_brand = normalize_text(candidate.get("brand"))
    vehicle = quote_context.get("vehicle") or quote_context.get("orbika") or quote_context
    brand_tokens = set(unique_tokens(vehicle.get("marca")))
    line_tokens = set(unique_tokens(vehicle.get("linea")))
    part_tokens = set(unique_tokens(part.get("part_name")))
    quote_year = vehicle.get("ano")
    quote_year_int = int(quote_year) if str(quote_year or "").isdigit() else None

    verdict = "no_evidence"
    summary = None
    citations: list[dict[str, Any]] = []

    for hit in hits:
        content = normalize_text(hit.get("content"))
        content_tokens = set(unique_tokens(content))
        vehicle_overlap = len((brand_tokens | line_tokens) & content_tokens)
        part_overlap = len(part_tokens & content_tokens)
        reference_supported = False
        if requested_ref and requested_ref in content:
            reference_supported = True
        if candidate_ref and candidate_ref in content:
            reference_supported = True

        years = years_covered(content)
        if quote_year_int and years and quote_year_int not in years and (reference_supported or vehicle_overlap >= 2):
            verdict = "year_scope_warning"
            summary = "Catalogo tecnico sugiere otra ventana de anos; validar modelo."
        elif reference_supported and vehicle_overlap >= 1:
            verdict = "reference_supported"
            summary = "Catalogo tecnico respalda referencia o aplicacion del vehiculo."
        elif vehicle_overlap >= 2 and part_overlap >= 1:
            verdict = "vehicle_supported"
            summary = "Fuente tecnica respalda la aplicacion para este vehiculo."
        elif part_overlap >= 2 or candidate_brand and candidate_brand in content:
            if verdict == "no_evidence":
                verdict = "generic_support"
                summary = "Fuente tecnica describe esta familia; validar referencia exacta."

        citations.append(
            {
                "title": hit.get("title"),
                "page_span": format_page_span(hit.get("page_start"), hit.get("page_end")),
                "score": round(float(hit.get("score") or 0), 4),
                "retrieval_mode": hit.get("retrieval_mode", "text"),
            }
        )

    if verdict == "no_evidence":
        return {"verdict": verdict, "summary": None, "citations": []}
    return {"verdict": verdict, "summary": summary, "citations": citations[:3]}


def print_ingest_summary(counters: IngestCounters, dry_run: bool) -> None:
    mode = "dry-run" if dry_run else "ingest"
    print(f"mode={mode}")
    print(
        f"documents: imported={counters.imported} updated={counters.updated} "
        f"skipped={counters.skipped} failed={counters.failed}"
    )
    print(f"chunks={counters.chunks}")
    print(f"embedded_chunks={counters.embedded_chunks}")
    for warning in counters.warnings:
        print(f"warning: {warning}")


def print_search_results(results: list[dict[str, Any]]) -> None:
    print(json.dumps(
        [
            {
                "title": row.get("title"),
                "file_path": row.get("file_path"),
                "page_span": format_page_span(row.get("page_start"), row.get("page_end")),
                "score": round(float(row.get("score") or 0), 4),
                "text_score": round(float(row.get("text_score") or 0), 4),
                "vector_score": round(float(row.get("vector_score") or 0), 4),
                "retrieval_mode": row.get("retrieval_mode", "text"),
                "excerpt": str(row.get("content") or "")[:320],
            }
            for row in results
        ],
        ensure_ascii=False,
        indent=2,
    ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest and search technical PDFs for Orbika RAG.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Load PDFs from knowledge/rag_sources into PostgreSQL.")
    ingest.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    ingest.add_argument("--limit", type=int)
    ingest.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ingest.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--skip-embeddings", action="store_true")

    search = subparsers.add_parser("search", help="Query indexed RAG chunks from PostgreSQL.")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT)
    search.add_argument("--mode", choices=("auto", "text", "vector", "hybrid"), default="auto")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    database_url = database_url_from_env()
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    if args.command == "ingest":
        files = source_files(args.source_dir, args.limit)
        if not files:
            print(f"No PDF files found in {args.source_dir}", file=sys.stderr)
            return 1
        counters = ingest_documents(
            files,
            database_url=database_url,
            dry_run=args.dry_run,
            max_chars=args.max_chars,
            overlap=args.overlap,
            skip_embeddings=args.skip_embeddings,
        )
        print_ingest_summary(counters, args.dry_run)
        return 1 if counters.failed else 0

    if args.command == "search":
        results = search_chunks(
            database_url=database_url,
            query=args.query,
            limit=args.limit,
            mode=args.mode,
        )
        print_search_results(results)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

