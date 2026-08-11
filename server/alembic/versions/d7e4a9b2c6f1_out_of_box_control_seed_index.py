"""add out-of-box control seed index

Revision ID: d7e4a9b2c6f1
Revises: f3a1c8d7e2b4
Create Date: 2026-08-10 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision = "d7e4a9b2c6f1"
down_revision = "f3a1c8d7e2b4"
branch_labels = None
depends_on = None

_INDEX_NAME = "idx_controls_namespace_seed_source"


def _index_is_invalid() -> bool:
    result = op.get_bind().execute(
        sa.text(
            """
            SELECT NOT pg_index.indisvalid
            FROM pg_index
            WHERE pg_index.indexrelid = to_regclass(:index_name)
            """
        ),
        {"index_name": _INDEX_NAME},
    )
    return bool(result.scalar_one_or_none())


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Offline generation has no live PostgreSQL catalog to inspect. Emitting
        # CREATE IF NOT EXISTS is safe there; invalid-index recovery remains an
        # online-only retry path.
        if not context.is_offline_mode() and _index_is_invalid():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME}
            ON controls (namespace_key, seed_source_id)
            WHERE seed_source_id IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
