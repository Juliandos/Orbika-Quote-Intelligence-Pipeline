"""Add RAG document and chunk tables.

Revision ID: 20260621_0002
Revises: 20260617_0001
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op

revision = "20260621_0002"
down_revision = "20260617_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rag_documents (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          title text NOT NULL,
          source_type text NOT NULL DEFAULT 'pdf',
          source_uri text,
          file_path text NOT NULL,
          sha256 text UNIQUE NOT NULL,
          language text,
          status text NOT NULL DEFAULT 'active',
          page_count integer NOT NULL DEFAULT 0,
          metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE rag_chunks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id uuid NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
          chunk_index integer NOT NULL,
          page_start integer,
          page_end integer,
          content text NOT NULL,
          content_normalized text NOT NULL,
          metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT rag_chunks_document_chunk_unique UNIQUE (document_id, chunk_index)
        );

        CREATE INDEX ix_rag_documents_status
          ON rag_documents (status);
        CREATE INDEX ix_rag_documents_file_path
          ON rag_documents (file_path);
        CREATE INDEX ix_rag_chunks_document_id
          ON rag_chunks (document_id);
        CREATE INDEX ix_rag_chunks_page_span
          ON rag_chunks (page_start, page_end);
        CREATE INDEX ix_rag_chunks_content_search
          ON rag_chunks
          USING GIN (to_tsvector('simple', content_normalized));

        CREATE TRIGGER set_updated_at_rag_documents
          BEFORE UPDATE ON rag_documents
          FOR EACH ROW
          EXECUTE FUNCTION set_updated_at();

        CREATE TRIGGER set_updated_at_rag_chunks
          BEFORE UPDATE ON rag_chunks
          FOR EACH ROW
          EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS set_updated_at_rag_chunks ON rag_chunks;
        DROP TRIGGER IF EXISTS set_updated_at_rag_documents ON rag_documents;
        DROP TABLE IF EXISTS rag_chunks;
        DROP TABLE IF EXISTS rag_documents;
        """
    )
