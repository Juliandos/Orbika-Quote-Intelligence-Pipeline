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
from pathlib import Path
from typing import Any


try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None


DEFAULT_SOURCE_DIR = Path("knowledge/rag_sources")
DEFAULT_MAX_CHARS = 1400
DEFAULT_OVERLAP = 180
DEFAULT_SEARCH_LIMIT = 5

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
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if len(self.warnings) < 50:
            self.warnings.append(message)


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


def upsert_document(
    cur: psycopg.Cursor,
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
    cur: psycopg.Cursor,
    *,
    document_id: str,
    chunks: list[dict[str, Any]],
) -> int:
    cur.execute("DELETE FROM rag_chunks WHERE document_id = %s", (document_id,))
    for chunk in chunks:
        cur.execute(
            """
            INSERT INTO rag_chunks (
              document_id, chunk_index, page_start, page_end,
              content, content_normalized, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                document_id,
                chunk["chunk_index"],
                chunk.get("page_start"),
                chunk.get("page_end"),
                chunk["content"],
                chunk["content_normalized"],
                jsonb(chunk.get("metadata") or {}),
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
                        chunk_count = replace_chunks(
                            cur,
                            document_id=document_id,
                            chunks=build_chunks(pages, max_chars=max_chars, overlap=overlap),
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


def search_chunks(
    *,
    database_url: str,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        return []
    sql = """
        SELECT
          d.title,
          d.file_path,
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

    hits = search_chunks(database_url=database_url, query=query, limit=limit)
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

    search = subparsers.add_parser("search", help="Query indexed RAG chunks from PostgreSQL.")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT)
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
        )
        print_ingest_summary(counters, args.dry_run)
        return 1 if counters.failed else 0

    if args.command == "search":
        results = search_chunks(database_url=database_url, query=args.query, limit=args.limit)
        print_search_results(results)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
