"""Switch RAG embeddings to local 384-dim vectors.

Revision ID: 20260625_0004
Revises: 20260625_0003
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op

revision = "20260625_0004"
down_revision = "20260625_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_rag_chunks_embedding_cosine;

        ALTER TABLE rag_chunks
          ALTER COLUMN embedding TYPE vector(384)
          USING NULL;

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

        ALTER TABLE rag_chunks
          ALTER COLUMN embedding TYPE vector(1536)
          USING NULL;

        CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_cosine
          ON rag_chunks
          USING ivfflat (embedding vector_cosine_ops)
          WITH (lists = 100);
        """
    )
