"""Add tenant scaffolding and targets schema.

Additive, behavior-preserving migration:

- Adds opaque string ``tenant_id`` columns to ``agents``, ``controls``,
  ``policies``, ``agent_controls``, and ``agent_policies``. Existing rows are
  backfilled to ``default-tenant`` and columns are then made NOT NULL. A
  DB-level ``server_default`` keeps writes that omit a tenant working.
- Creates new tables ``targets`` and ``target_controls``. Uniqueness on
  ``targets`` covers ``(tenant_id, target_type, external_id)`` and on
  ``target_controls`` covers ``(target_id, control_id)``.
  ``target_controls.target_id`` uses ``ON DELETE CASCADE`` because the
  attachment has no meaning without its target; ``control_id`` uses the
  default restrictive behavior so control deletion does not silently cascade
  into attachment cleanup.
- Intentionally omitted from this migration (to be addressed separately):
    * ``policy_controls.tenant_id`` (tenant scope inherited transitively
      through ``policy_id`` and ``control_id``).
    * ``control_execution_events.tenant_id`` (observability tables out of
      scope here).
    * ``updated_at`` columns (no established auto-maintenance pattern in the
      repo yet).
    * Indexes on the new ``tenant_id`` columns (read paths do not filter on
      tenant yet, so unused indexes would just add write cost).

Revision ID: 7c1a9b4e2d30
Revises: 5f2b5f4e1a90
Create Date: 2026-04-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "7c1a9b4e2d30"
down_revision = "5f2b5f4e1a90"
branch_labels = None
depends_on = None


DEFAULT_TENANT_ID = "default-tenant"

_TENANT_SCOPED_TABLES = (
    "agents",
    "controls",
    "policies",
    "agent_controls",
    "agent_policies",
)


def upgrade() -> None:
    # Step 1: add tenant_id as nullable on all affected tables.
    for table in _TENANT_SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.String(length=64), nullable=True),
        )

    # Step 2: backfill existing rows to the synthetic default tenant.
    for table in _TENANT_SCOPED_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET tenant_id = :tenant WHERE tenant_id IS NULL"
            ).bindparams(tenant=DEFAULT_TENANT_ID)
        )

    # Step 3: make tenant_id NOT NULL and install the DB-level default so
    # unscoped OSS writes continue to land in the default tenant automatically.
    for table in _TENANT_SCOPED_TABLES:
        op.alter_column(
            table,
            "tenant_id",
            existing_type=sa.String(length=64),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        )

    # Step 4: create the new target schema objects.
    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "data",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "target_type",
            "external_id",
            name="uq_targets_tenant_type_external_id",
        ),
    )

    op.create_table(
        "target_controls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["targets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["control_id"], ["controls.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_id", "control_id", name="uq_target_controls_target_control"
        ),
    )
    op.create_index(
        op.f("ix_target_controls_target_id"),
        "target_controls",
        ["target_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_target_controls_control_id"),
        "target_controls",
        ["control_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_target_controls_control_id"), table_name="target_controls"
    )
    op.drop_index(
        op.f("ix_target_controls_target_id"), table_name="target_controls"
    )
    op.drop_table("target_controls")
    op.drop_table("targets")

    for table in _TENANT_SCOPED_TABLES:
        op.drop_column(table, "tenant_id")
