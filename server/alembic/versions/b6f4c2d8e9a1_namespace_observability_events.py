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


_EVENT_TABLE = "control_execution_events"
_NAMESPACE_COLUMN = "namespace_key"
_TARGET_PK_COLUMNS = ["namespace_key", "control_execution_id"]
_LEGACY_PK_COLUMNS = ["control_execution_id"]


def _column_names() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_EVENT_TABLE)}


def _replace_primary_key(columns: list[str]) -> None:
    pk = sa.inspect(op.get_bind()).get_pk_constraint(_EVENT_TABLE)
    current_columns = list(pk.get("constrained_columns") or [])
    if current_columns == columns:
        return

    constraint_name = pk.get("name")
    if constraint_name:
        op.drop_constraint(constraint_name, _EVENT_TABLE, type_="primary")
    op.create_primary_key("control_execution_events_pkey", _EVENT_TABLE, columns)


def upgrade() -> None:
    if _NAMESPACE_COLUMN not in _column_names():
        op.add_column(
            _EVENT_TABLE,
            sa.Column(
                _NAMESPACE_COLUMN,
                sa.String(length=255),
                server_default=sa.text("'default'"),
                nullable=False,
            ),
        )
    _replace_primary_key(_TARGET_PK_COLUMNS)
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
    if _NAMESPACE_COLUMN in _column_names():
        _replace_primary_key(_LEGACY_PK_COLUMNS)
        op.drop_column(_EVENT_TABLE, _NAMESPACE_COLUMN)
