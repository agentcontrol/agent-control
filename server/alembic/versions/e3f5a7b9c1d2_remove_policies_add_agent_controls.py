"""Remove policies, add direct agent_controls relationship.

Revision ID: e3f5a7b9c1d2
Revises: d2f4a6b8c9d0
Create Date: 2026-02-10

This migration:
1. Creates agent_controls junction table (agent_uuid, control_id)
2. Migrates data: policy_controls + agents.policy_id -> agent_controls
3. Drops agents.policy_id column and its index
4. Drops policy_controls table
5. Drops policies table
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e3f5a7b9c1d2"
down_revision = "d2f4a6b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create agent_controls junction table
    op.create_table(
        "agent_controls",
        sa.Column(
            "agent_uuid",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.agent_uuid"),
            primary_key=True,
        ),
        sa.Column(
            "control_id",
            sa.Integer(),
            sa.ForeignKey("controls.id"),
            primary_key=True,
        ),
    )
    op.create_index("ix_agent_controls_agent_uuid", "agent_controls", ["agent_uuid"])
    op.create_index("ix_agent_controls_control_id", "agent_controls", ["control_id"])

    # 2. Migrate data: for each agent with a policy_id, copy the policy's controls
    # into agent_controls with that agent's agent_uuid
    op.execute(
        """
        INSERT INTO agent_controls (agent_uuid, control_id)
        SELECT a.agent_uuid, pc.control_id
        FROM agents a
        JOIN policy_controls pc ON a.policy_id = pc.policy_id
        ON CONFLICT DO NOTHING
        """
    )

    # 3. Drop agents.policy_id column (and its index)
    op.drop_index("ix_agents_policy_id", table_name="agents")
    op.drop_column("agents", "policy_id")

    # 4. Drop policy_controls table
    op.drop_index("ix_policy_controls_control_id", table_name="policy_controls")
    op.drop_index("ix_policy_controls_policy_id", table_name="policy_controls")
    op.drop_table("policy_controls")

    # 5. Drop policies table
    op.drop_table("policies")


def downgrade() -> None:
    # Recreate policies table
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
    )

    # Recreate policy_controls junction table
    op.create_table(
        "policy_controls",
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("policies.id"),
            primary_key=True,
        ),
        sa.Column(
            "control_id",
            sa.Integer(),
            sa.ForeignKey("controls.id"),
            primary_key=True,
        ),
    )
    op.create_index("ix_policy_controls_policy_id", "policy_controls", ["policy_id"])
    op.create_index("ix_policy_controls_control_id", "policy_controls", ["control_id"])

    # Recreate agents.policy_id column
    op.add_column(
        "agents",
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("policies.id"), nullable=True),
    )
    op.create_index("ix_agents_policy_id", "agents", ["policy_id"])

    # Note: Data migration back from agent_controls to policies is not possible
    # because the original policy names and groupings are lost.

    # Drop agent_controls
    op.drop_index("ix_agent_controls_control_id", table_name="agent_controls")
    op.drop_index("ix_agent_controls_agent_uuid", table_name="agent_controls")
    op.drop_table("agent_controls")
