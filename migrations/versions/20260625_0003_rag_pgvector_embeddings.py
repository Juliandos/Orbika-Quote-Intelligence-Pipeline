"""Enable pgvector storage for RAG chunk embeddings.

Revision ID: 20260625_0003
Revises: 20260621_0002
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op

revision = "20260625_0003"
down_revision = "20260621_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS vector;

        ALTER TABLE rag_chunks
          ADD COLUMN IF NOT EXISTS embedding vector(1536),
          ADD COLUMN IF NOT EXISTS embedding_model text,
          ADD COLUMN IF NOT EXISTS embedding_dimensions integer,
          ADD COLUMN IF NOT EXISTS embedded_at timestamptz;

        CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_model
          ON rag_chunks (embedding_model);

        CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_cosine
          ON rag_chunks
          USING ivfflat (embedding vector_cosine_ops)
          WITH (lists = 100);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_rag_chunks_embedding_cosine;
        DROP INDEX IF EXISTS ix_rag_chunks_embedding_model;

        ALTER TABLE rag_chunks
          DROP COLUMN IF EXISTS embedded_at,
          DROP COLUMN IF EXISTS embedding_dimensions,
          DROP COLUMN IF EXISTS embedding_model,
          DROP COLUMN IF EXISTS embedding;

        DROP EXTENSION IF EXISTS vector;
        """
    )
