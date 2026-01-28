"""Rename plugin column to evaluator in evaluator_configs table.

Revision ID: c8d9e0f1a2b3
Revises: b7c9d8e1f2a3
Create Date: 2026-01-28 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "c8d9e0f1a2b3"
down_revision = "b7c9d8e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename plugin column to evaluator
    op.alter_column(
        "evaluator_configs",
        "plugin",
        new_column_name="evaluator",
    )
    # Rename the index
    op.drop_index("ix_evaluator_configs_plugin", table_name="evaluator_configs")
    op.create_index(
        "ix_evaluator_configs_evaluator",
        "evaluator_configs",
        ["evaluator"],
        unique=False,
    )


def downgrade() -> None:
    # Rename evaluator column back to plugin
    op.alter_column(
        "evaluator_configs",
        "evaluator",
        new_column_name="plugin",
    )
    # Rename the index back
    op.drop_index("ix_evaluator_configs_evaluator", table_name="evaluator_configs")
    op.create_index(
        "ix_evaluator_configs_plugin",
        "evaluator_configs",
        ["plugin"],
        unique=False,
    )
