"""namespace observability events

Revision ID: b6f4c2d8e9a1
Revises: a7f3b1e0d9c5
Create Date: 2026-05-14 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b6f4c2d8e9a1"
down_revision = "a7f3b1e0d9c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "control_execution_events",
        sa.Column(
            "namespace_key",
            sa.String(length=255),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
    )
    op.drop_constraint(
        "control_execution_events_pkey",
        "control_execution_events",
        type_="primary",
    )
    op.create_primary_key(
        "control_execution_events_pkey",
        "control_execution_events",
        ["namespace_key", "control_execution_id"],
    )
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_events_agent_time")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_events_namespace_agent_time
            ON control_execution_events (namespace_key, agent_name, timestamp DESC)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_events_namespace_agent_time")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_events_agent_time
            ON control_execution_events (agent_name, timestamp DESC)
            """
        )
    op.drop_constraint(
        "control_execution_events_pkey",
        "control_execution_events",
        type_="primary",
    )
    op.create_primary_key(
        "control_execution_events_pkey",
        "control_execution_events",
        ["control_execution_id"],
    )
    op.drop_column("control_execution_events", "namespace_key")
