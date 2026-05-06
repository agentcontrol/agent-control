"""namespace scoping and control bindings

Adds a `namespace_key` scoping column to all six core tables, replaces
single-column uniqueness with namespace-scoped composite uniqueness, converts
foreign keys on association tables to composite same-namespace foreign keys,
and creates the new `control_bindings` table for target-attached controls.

OSS / single-namespace deployments are preserved by the `'default'` server
default on every new `namespace_key` column.

Downgrade caveat: once cross-namespace data exists (two rows with the same
natural-key in different namespaces), restoring the original global
single-column uniqueness is not possible. The downgrade asserts that no such
duplicates exist and aborts with a clear error if they do.

Revision ID: a7f3b1e0d9c5
Revises: c1e9f9c4a1d2
Create Date: 2026-04-27 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7f3b1e0d9c5"
down_revision = "c1e9f9c4a1d2"
branch_labels = None
depends_on = None


_NAMESPACE_DEFAULT = sa.text("'default'")


def upgrade() -> None:
    # 1. Add namespace_key column to all six core tables.
    for table in (
        "agents",
        "controls",
        "policies",
        "agent_controls",
        "agent_policies",
        "policy_controls",
    ):
        op.add_column(
            table,
            sa.Column(
                "namespace_key",
                sa.String(255),
                nullable=False,
                server_default=_NAMESPACE_DEFAULT,
            ),
        )

    # 2. Drop existing foreign keys on association tables. All are being
    #    replaced with composite same-namespace foreign keys.
    op.drop_constraint(
        "agent_controls_agent_name_fkey", "agent_controls", type_="foreignkey"
    )
    op.drop_constraint(
        "agent_controls_control_id_fkey", "agent_controls", type_="foreignkey"
    )
    op.drop_constraint(
        "agent_policies_agent_name_fkey", "agent_policies", type_="foreignkey"
    )
    op.drop_constraint(
        "agent_policies_policy_id_fkey", "agent_policies", type_="foreignkey"
    )
    op.drop_constraint(
        "policy_controls_policy_id_fkey", "policy_controls", type_="foreignkey"
    )
    op.drop_constraint(
        "policy_controls_control_id_fkey", "policy_controls", type_="foreignkey"
    )

    # 3. Drop existing primary keys, unique constraints, and partial unique
    #    index that are about to be replaced.
    op.drop_constraint("agents_pkey", "agents", type_="primary")
    op.drop_constraint("policies_name_key", "policies", type_="unique")
    op.drop_index("idx_controls_name_active", table_name="controls")
    op.drop_constraint("agent_controls_pkey", "agent_controls", type_="primary")
    op.drop_constraint("agent_policies_pkey", "agent_policies", type_="primary")
    op.drop_constraint("policy_controls_pkey", "policy_controls", type_="primary")

    # 4. Add namespace-scoped uniqueness. controls.id and policies.id remain
    #    primary keys; the additional UNIQUE (namespace_key, id) on each is
    #    required so composite same-namespace foreign keys can target them.
    op.create_primary_key("agents_pkey", "agents", ["namespace_key", "name"])
    op.create_unique_constraint(
        "uq_policies_namespace_name", "policies", ["namespace_key", "name"]
    )
    op.create_index(
        "idx_controls_namespace_name_active",
        "controls",
        ["namespace_key", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_unique_constraint(
        "uq_controls_namespace_id", "controls", ["namespace_key", "id"]
    )
    op.create_unique_constraint(
        "uq_policies_namespace_id", "policies", ["namespace_key", "id"]
    )
    op.create_primary_key(
        "agent_controls_pkey",
        "agent_controls",
        ["namespace_key", "agent_name", "control_id"],
    )
    op.create_primary_key(
        "agent_policies_pkey",
        "agent_policies",
        ["namespace_key", "agent_name", "policy_id"],
    )
    op.create_primary_key(
        "policy_controls_pkey",
        "policy_controls",
        ["namespace_key", "policy_id", "control_id"],
    )

    # 5. Add composite same-namespace foreign keys on association tables.
    op.create_foreign_key(
        "agent_controls_agent_fkey",
        "agent_controls",
        "agents",
        ["namespace_key", "agent_name"],
        ["namespace_key", "name"],
    )
    op.create_foreign_key(
        "agent_controls_control_fkey",
        "agent_controls",
        "controls",
        ["namespace_key", "control_id"],
        ["namespace_key", "id"],
    )
    op.create_foreign_key(
        "agent_policies_agent_fkey",
        "agent_policies",
        "agents",
        ["namespace_key", "agent_name"],
        ["namespace_key", "name"],
    )
    op.create_foreign_key(
        "agent_policies_policy_fkey",
        "agent_policies",
        "policies",
        ["namespace_key", "policy_id"],
        ["namespace_key", "id"],
    )
    op.create_foreign_key(
        "policy_controls_policy_fkey",
        "policy_controls",
        "policies",
        ["namespace_key", "policy_id"],
        ["namespace_key", "id"],
    )
    op.create_foreign_key(
        "policy_controls_control_fkey",
        "policy_controls",
        "controls",
        ["namespace_key", "control_id"],
        ["namespace_key", "id"],
    )

    # 6. Create the control_bindings table. Each row attaches one control to
    #    one target; uniqueness is enforced on
    #    (namespace_key, target_type, target_id, control_id).
    #
    #    Per-agent overrides and exemptions within a target are intentionally
    #    out of scope at this stage. If they become a product requirement, two
    #    forward paths exist:
    #      - re-introduce an `agent_name` column with a partial-index pair
    #        and an `enabled`-aware most-specific-wins resolver (supports
    #        both additions and exemptions)
    #      - or merge target-bearing resolution with the existing
    #        `agent_controls` table at runtime (supports per-agent additions
    #        only; exemptions still need a schema change)
    op.create_table(
        "control_bindings",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "namespace_key",
            sa.String(255),
            nullable=False,
            server_default=_NAMESPACE_DEFAULT,
        ),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
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
        sa.PrimaryKeyConstraint("id", name="control_bindings_pkey"),
        sa.ForeignKeyConstraint(
            ["namespace_key", "control_id"],
            ["controls.namespace_key", "controls.id"],
            name="control_bindings_control_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "namespace_key",
            "target_type",
            "target_id",
            "control_id",
            name="uq_control_bindings_target_control",
        ),
    )
    op.create_index(
        "idx_control_bindings_lookup",
        "control_bindings",
        ["namespace_key", "target_type", "target_id"],
    )
    # Leading-control_id index covers list_bindings(control_id=...) and the
    # ON DELETE CASCADE path from controls.
    op.create_index(
        "idx_control_bindings_control",
        "control_bindings",
        ["namespace_key", "control_id"],
    )

    # 7. Restore natural-key index coverage. The composite primary keys and
    #    unique constraints lead with namespace_key, so name-only lookups
    #    (existing service code) no longer have a leading-column index. These
    #    plain indexes preserve that lookup shape during the rollout window.
    #    The controls index mirrors the partial filter on the existing
    #    name-based call sites, which all require deleted_at IS NULL.
    op.create_index("ix_agents_name", "agents", ["name"])
    op.create_index("ix_policies_name", "policies", ["name"])
    op.create_index(
        "ix_controls_name",
        "controls",
        ["name"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Refuse to downgrade if cross-namespace data exists; restoring the
    # original global single-column uniqueness would fail or lose data.
    bind = op.get_bind()
    for table, natural_key in (
        ("agents", "name"),
        ("policies", "name"),
    ):
        result = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM ("  # noqa: S608 (table/column names are constants)
                f"  SELECT {natural_key} FROM {table}"
                f"  GROUP BY {natural_key} HAVING COUNT(DISTINCT namespace_key) > 1"
                f") AS dupes"
            )
        ).scalar_one()
        if result:
            raise RuntimeError(
                f"Cannot downgrade: {table} contains {natural_key} values that "
                f"appear in more than one namespace. Restoring global "
                f"uniqueness would conflict. Resolve duplicates before "
                f"downgrading."
            )
    # controls uses a partial unique index on (namespace_key, name) where
    # deleted_at IS NULL, so the equivalent check filters out soft-deleted
    # rows.
    result = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "  SELECT name FROM controls WHERE deleted_at IS NULL"
            "  GROUP BY name HAVING COUNT(DISTINCT namespace_key) > 1"
            ") AS dupes"
        )
    ).scalar_one()
    if result:
        raise RuntimeError(
            "Cannot downgrade: controls contains live name values that appear "
            "in more than one namespace. Restoring global uniqueness would "
            "conflict. Resolve duplicates before downgrading."
        )

    # 1. Drop natural-key indexes added by upgrade.
    op.drop_index("ix_controls_name", table_name="controls")
    op.drop_index("ix_policies_name", table_name="policies")
    op.drop_index("ix_agents_name", table_name="agents")

    # 2. Drop control_bindings.
    op.drop_index("idx_control_bindings_control", table_name="control_bindings")
    op.drop_index("idx_control_bindings_lookup", table_name="control_bindings")
    op.drop_table("control_bindings")

    # 3. Drop composite same-namespace foreign keys on association tables.
    op.drop_constraint(
        "policy_controls_control_fkey", "policy_controls", type_="foreignkey"
    )
    op.drop_constraint(
        "policy_controls_policy_fkey", "policy_controls", type_="foreignkey"
    )
    op.drop_constraint(
        "agent_policies_policy_fkey", "agent_policies", type_="foreignkey"
    )
    op.drop_constraint(
        "agent_policies_agent_fkey", "agent_policies", type_="foreignkey"
    )
    op.drop_constraint(
        "agent_controls_control_fkey", "agent_controls", type_="foreignkey"
    )
    op.drop_constraint(
        "agent_controls_agent_fkey", "agent_controls", type_="foreignkey"
    )

    # 4. Drop namespace-scoped uniqueness and primary keys.
    op.drop_constraint("policy_controls_pkey", "policy_controls", type_="primary")
    op.drop_constraint("agent_policies_pkey", "agent_policies", type_="primary")
    op.drop_constraint("agent_controls_pkey", "agent_controls", type_="primary")
    op.drop_constraint("uq_policies_namespace_id", "policies", type_="unique")
    op.drop_constraint("uq_controls_namespace_id", "controls", type_="unique")
    op.drop_index("idx_controls_namespace_name_active", table_name="controls")
    op.drop_constraint("uq_policies_namespace_name", "policies", type_="unique")
    op.drop_constraint("agents_pkey", "agents", type_="primary")

    # 5. Restore original primary keys, unique constraint, and partial unique
    #    index on the natural-key columns.
    op.create_primary_key("agents_pkey", "agents", ["name"])
    op.create_unique_constraint("policies_name_key", "policies", ["name"])
    op.create_index(
        "idx_controls_name_active",
        "controls",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_primary_key(
        "agent_controls_pkey", "agent_controls", ["agent_name", "control_id"]
    )
    op.create_primary_key(
        "agent_policies_pkey", "agent_policies", ["agent_name", "policy_id"]
    )
    op.create_primary_key(
        "policy_controls_pkey", "policy_controls", ["policy_id", "control_id"]
    )

    # 6. Restore original single-column foreign keys on association tables.
    op.create_foreign_key(
        "agent_controls_agent_name_fkey",
        "agent_controls",
        "agents",
        ["agent_name"],
        ["name"],
    )
    op.create_foreign_key(
        "agent_controls_control_id_fkey",
        "agent_controls",
        "controls",
        ["control_id"],
        ["id"],
    )
    op.create_foreign_key(
        "agent_policies_agent_name_fkey",
        "agent_policies",
        "agents",
        ["agent_name"],
        ["name"],
    )
    op.create_foreign_key(
        "agent_policies_policy_id_fkey",
        "agent_policies",
        "policies",
        ["policy_id"],
        ["id"],
    )
    op.create_foreign_key(
        "policy_controls_policy_id_fkey",
        "policy_controls",
        "policies",
        ["policy_id"],
        ["id"],
    )
    op.create_foreign_key(
        "policy_controls_control_id_fkey",
        "policy_controls",
        "controls",
        ["control_id"],
        ["id"],
    )

    # 7. Drop namespace_key columns.
    for table in (
        "policy_controls",
        "agent_policies",
        "agent_controls",
        "policies",
        "controls",
        "agents",
    ):
        op.drop_column(table, "namespace_key")
