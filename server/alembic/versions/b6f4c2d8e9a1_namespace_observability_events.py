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
    op.create_index(
        "ix_events_namespace_agent_time",
        "control_execution_events",
        ["namespace_key", "agent_name", sa.literal_column("timestamp DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_events_namespace_agent_time",
        table_name="control_execution_events",
    )
    op.drop_column("control_execution_events", "namespace_key")
