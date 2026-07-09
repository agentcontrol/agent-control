"""access users, single-active API keys, and user-owned control grants

Revision ID: f7c2a9d4e1b8
Revises: e2b7f4a9c6d1
Create Date: 2026-07-09 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f7c2a9d4e1b8"
down_revision = "e2b7f4a9c6d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "namespace_key",
            sa.String(length=255),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), server_default=sa.text("'member'"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("TRUE"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_access_users_role"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace_key", "id", name="uq_access_users_namespace_id"),
        sa.UniqueConstraint("namespace_key", "name", name="uq_access_users_namespace_name"),
    )

    op.create_table(
        "api_key_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "namespace_key",
            sa.String(length=255),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("TRUE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["namespace_key", "user_id"],
            ["access_users.namespace_key", "access_users.id"],
            name="api_key_credentials_user_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace_key", "id", name="uq_api_key_credentials_namespace_id"),
        sa.UniqueConstraint("key_hash", name="uq_api_key_credentials_key_hash"),
    )
    op.create_index(
        "idx_api_key_credentials_user",
        "api_key_credentials",
        ["namespace_key", "user_id"],
    )
    op.create_index(
        "uq_api_key_credentials_one_live_per_user",
        "api_key_credentials",
        ["namespace_key", "user_id"],
        unique=True,
        postgresql_where=sa.text("enabled IS TRUE AND revoked_at IS NULL"),
    )

    op.create_table(
        "access_user_control_grants",
        sa.Column(
            "namespace_key",
            sa.String(length=255),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["namespace_key", "user_id"],
            ["access_users.namespace_key", "access_users.id"],
            name="access_user_control_grants_user_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["namespace_key", "control_id"],
            ["controls.namespace_key", "controls.id"],
            name="access_user_control_grants_control_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "namespace_key",
            "user_id",
            "control_id",
            name="access_user_control_grants_pkey",
        ),
    )
    op.create_index(
        "idx_access_user_control_grants_control",
        "access_user_control_grants",
        ["namespace_key", "control_id"],
    )

    op.add_column(
        "control_execution_events",
        sa.Column("access_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "control_execution_events",
        sa.Column("api_key_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "control_execution_events_access_user_fkey",
        "control_execution_events",
        "access_users",
        ["namespace_key", "access_user_id"],
        ["namespace_key", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_events_namespace_user_agent_time",
        "control_execution_events",
        ["namespace_key", "access_user_id", "agent_name", sa.text("timestamp DESC")],
    )
    op.create_foreign_key(
        "control_execution_events_api_key_fkey",
        "control_execution_events",
        "api_key_credentials",
        ["namespace_key", "api_key_id"],
        ["namespace_key", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_events_namespace_credential_time",
        "control_execution_events",
        ["namespace_key", "api_key_id", sa.text("timestamp DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_events_namespace_credential_time", table_name="control_execution_events")
    op.drop_constraint(
        "control_execution_events_api_key_fkey",
        "control_execution_events",
        type_="foreignkey",
    )
    op.drop_index("ix_events_namespace_user_agent_time", table_name="control_execution_events")
    op.drop_constraint(
        "control_execution_events_access_user_fkey",
        "control_execution_events",
        type_="foreignkey",
    )
    op.drop_column("control_execution_events", "access_user_id")
    op.drop_column("control_execution_events", "api_key_id")
    op.drop_index(
        "idx_access_user_control_grants_control",
        table_name="access_user_control_grants",
    )
    op.drop_table("access_user_control_grants")
    op.drop_index(
        "uq_api_key_credentials_one_live_per_user",
        table_name="api_key_credentials",
    )
    op.drop_index("idx_api_key_credentials_user", table_name="api_key_credentials")
    op.drop_table("api_key_credentials")
    op.drop_table("access_users")
