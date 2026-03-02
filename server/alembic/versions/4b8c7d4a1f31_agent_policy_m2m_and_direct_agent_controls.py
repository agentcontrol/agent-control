"""agent policy m2m and direct agent controls

Revision ID: 4b8c7d4a1f31
Revises: 58920e6807fe
Create Date: 2026-03-02 16:15:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4b8c7d4a1f31"
down_revision = "58920e6807fe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_controls",
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agent_name"], ["agents.name"]),
        sa.ForeignKeyConstraint(["control_id"], ["controls.id"]),
        sa.PrimaryKeyConstraint("agent_name", "control_id"),
    )
    op.create_index(op.f("ix_agent_controls_agent_name"), "agent_controls", ["agent_name"])
    op.create_index(op.f("ix_agent_controls_control_id"), "agent_controls", ["control_id"])

    op.create_table(
        "agent_policies",
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agent_name"], ["agents.name"]),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.id"]),
        sa.PrimaryKeyConstraint("agent_name", "policy_id"),
    )
    op.create_index(op.f("ix_agent_policies_agent_name"), "agent_policies", ["agent_name"])
    op.create_index(op.f("ix_agent_policies_policy_id"), "agent_policies", ["policy_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO agent_policies (agent_name, policy_id)
            SELECT name, policy_id
            FROM agents
            WHERE policy_id IS NOT NULL
            ON CONFLICT (agent_name, policy_id) DO NOTHING
            """
        )
    )

    op.drop_index(op.f("ix_agents_policy_id"), table_name="agents")
    op.drop_constraint(op.f("agents_policy_id_fkey"), "agents", type_="foreignkey")
    op.drop_column("agents", "policy_id")


def downgrade() -> None:
    # NOTE: Downgrade can only restore one policy per agent via agents.policy_id.
    # If multiple policies are associated to an agent, all but MIN(policy_id) are lost.
    op.add_column("agents", sa.Column("policy_id", sa.Integer(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE agents AS a
            SET policy_id = ap.policy_id
            FROM (
                SELECT agent_name, MIN(policy_id) AS policy_id
                FROM agent_policies
                GROUP BY agent_name
            ) AS ap
            WHERE a.name = ap.agent_name
            """
        )
    )

    op.create_foreign_key(op.f("agents_policy_id_fkey"), "agents", "policies", ["policy_id"], ["id"])
    op.create_index(op.f("ix_agents_policy_id"), "agents", ["policy_id"])

    op.drop_index(op.f("ix_agent_policies_policy_id"), table_name="agent_policies")
    op.drop_index(op.f("ix_agent_policies_agent_name"), table_name="agent_policies")
    op.drop_table("agent_policies")

    # Direct agent-control links have no representation in the downgraded schema.
    op.drop_index(op.f("ix_agent_controls_control_id"), table_name="agent_controls")
    op.drop_index(op.f("ix_agent_controls_agent_name"), table_name="agent_controls")
    op.drop_table("agent_controls")
