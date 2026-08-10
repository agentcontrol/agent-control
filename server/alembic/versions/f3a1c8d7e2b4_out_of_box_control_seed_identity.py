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

_CANONICAL_NAME_SEED_SOURCE_ID = "oob-only-approved-tools-may-run"


def upgrade() -> None:
    op.add_column("controls", sa.Column("seed_source_id", sa.String(length=255), nullable=True))
    op.add_column(
        "controls",
        sa.Column("seed_opted_out_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Older servers reject ``canonical_name`` selectors. Retire only the seeded
    # control that still uses that selector, and make both its current payload
    # and historical snapshots parseable before rolling the application back.
    op.execute(
        f"""
        UPDATE control_versions AS version
        SET snapshot = jsonb_set(
            version.snapshot,
            '{{data,condition,selector,path}}',
            '"name"'::jsonb
        )
        FROM controls AS control
        WHERE version.control_id = control.id
          AND control.seed_source_id = '{_CANONICAL_NAME_SEED_SOURCE_ID}'
          AND version.snapshot #>> '{{data,condition,selector,path}}' = 'canonical_name'
        """
    )
    op.execute(
        f"""
        UPDATE controls
        SET data = jsonb_set(
                data,
                '{{condition,selector,path}}',
                '"name"'::jsonb
            ),
            deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP)
        WHERE seed_source_id = '{_CANONICAL_NAME_SEED_SOURCE_ID}'
          AND data #>> '{{condition,selector,path}}' = 'canonical_name'
        """
    )
    op.drop_column("controls", "seed_opted_out_at")
    op.drop_column("controls", "seed_source_id")
