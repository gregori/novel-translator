"""Initial working copies schema.

Revision ID: 0001
Revises:
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the working copy table with one active copy per run."""
    op.create_table(
        "working_copies",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("base_artifact_kind", sa.String(length=32), nullable=False),
        sa.Column("base_artifact_id", sa.String(length=32), nullable=True),
        sa.Column("base_content_hash", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_working_copies_run_id"),
    )


def downgrade() -> None:
    """Remove the working copy table."""
    op.drop_table("working_copies")
