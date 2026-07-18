"""merge rag and graph migration heads

Revision ID: 20260714_0005
Revises: 20260625_0004, 20260714_0004
Create Date: 2026-07-14 00:00:00.000000
"""

from __future__ import annotations

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = "20260714_0005"
down_revision = ("20260625_0004", "20260714_0004")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
