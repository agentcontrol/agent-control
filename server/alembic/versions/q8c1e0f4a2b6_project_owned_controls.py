"""Add explicit project ownership without reassigning legacy definitions.

Revision ID: q8c1e0f4a2b6
Revises: d7e4a9b2c6f1
"""

import sqlalchemy as sa
from alembic import op

revision = "q8c1e0f4a2b6"
down_revision = "d7e4a9b2c6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_project_scopes",
        sa.Column("namespace_key", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.CheckConstraint(
            "state IN ('active', 'deleting', 'deleted')", name="ck_control_project_scope_state"
        ),
    )
    op.add_column("controls", sa.Column("owner_project_id", sa.String(255), nullable=True))
    op.create_table(
        "control_target_scopes",
        sa.Column("namespace_key", sa.String(255), primary_key=True),
        sa.Column("target_type", sa.String(255), primary_key=True),
        sa.Column("target_id", sa.String(255), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.CheckConstraint(
            "state IN ('active', 'deleting', 'deleted')", name="ck_control_target_scope_state"
        ),
        sa.ForeignKeyConstraint(
            ["namespace_key", "project_id"],
            ["control_project_scopes.namespace_key", "control_project_scopes.project_id"],
        ),
    )
    op.create_foreign_key(
        "controls_owner_project_fkey",
        "controls",
        "control_project_scopes",
        ["namespace_key", "owner_project_id"],
        ["namespace_key", "project_id"],
    )
    op.create_index(
        "idx_controls_namespace_owner", "controls", ["namespace_key", "owner_project_id"]
    )


def downgrade() -> None:
    # Downgrading must not silently turn project-private records into org data.
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT 1 FROM controls WHERE owner_project_id IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError("Cannot remove ownership while project-owned controls exist")
    op.drop_index("idx_controls_namespace_owner", table_name="controls")
    op.drop_constraint("controls_owner_project_fkey", "controls", type_="foreignkey")
    op.drop_column("controls", "owner_project_id")
    op.drop_table("control_target_scopes")
    op.drop_table("control_project_scopes")
