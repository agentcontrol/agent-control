"""Rename evaluator_plugin column in observability events.

Revision ID: d2f4a6b8c9d0
Revises: simplify_observability_schema
Create Date: 2026-01-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d2f4a6b8c9d0"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = inspector.get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def upgrade() -> None:
    if _column_exists("control_execution_events", "evaluator_plugin"):
        op.alter_column(
            "control_execution_events",
            "evaluator_plugin",
            new_column_name="evaluator_name",
        )


def downgrade() -> None:
    if _column_exists("control_execution_events", "evaluator_name"):
        op.alter_column(
            "control_execution_events",
            "evaluator_name",
            new_column_name="evaluator_plugin",
        )
