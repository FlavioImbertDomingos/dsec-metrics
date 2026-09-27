"""Rate limit counters.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start", name=op.f("pk_rate_limits")),
        prefixes=["UNLOGGED"],
    )


def downgrade() -> None:
    op.drop_table("rate_limits")
