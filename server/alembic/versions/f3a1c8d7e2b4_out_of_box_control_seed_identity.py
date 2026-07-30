"""add immutable out-of-box control seed identity

Revision ID: f3a1c8d7e2b4
Revises: e2b7f4a9c6d1
Create Date: 2026-07-30 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a1c8d7e2b4"
down_revision = "e2b7f4a9c6d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("controls", sa.Column("seed_source_id", sa.String(length=255), nullable=True))
    op.add_column(
        "controls",
        sa.Column("seed_opted_out_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_controls_namespace_seed_source",
        "controls",
        ["namespace_key", "seed_source_id"],
        unique=True,
        postgresql_where=sa.text("seed_source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_controls_namespace_seed_source", table_name="controls")
    op.drop_column("controls", "seed_opted_out_at")
    op.drop_column("controls", "seed_source_id")
