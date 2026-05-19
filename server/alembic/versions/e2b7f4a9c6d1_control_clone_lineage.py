"""control clone lineage

Revision ID: e2b7f4a9c6d1
Revises: b6f4c2d8e9a1
Create Date: 2026-05-19 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2b7f4a9c6d1"
down_revision = "b6f4c2d8e9a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "controls",
        sa.Column("cloned_from_control_id", sa.Integer(), nullable=True),
    )
    # No ON DELETE action: hard deletes of clone sources are restricted.
    # The API soft-deletes controls so clone lineage remains intact.
    op.create_foreign_key(
        "controls_cloned_from_control_fkey",
        "controls",
        "controls",
        ["namespace_key", "cloned_from_control_id"],
        ["namespace_key", "id"],
    )
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_controls_cloned_from
            ON controls (namespace_key, cloned_from_control_id)
            WHERE cloned_from_control_id IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_controls_cloned_from")
    op.drop_constraint(
        "controls_cloned_from_control_fkey",
        "controls",
        type_="foreignkey",
    )
    op.drop_column("controls", "cloned_from_control_id")
