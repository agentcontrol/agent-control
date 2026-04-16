"""add control store publication tables and clone provenance

Revision ID: 7d9c2f1a3b44
Revises: c1e9f9c4a1d2
Create Date: 2026-04-15 16:30:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "7d9c2f1a3b44"
down_revision = "c1e9f9c4a1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_stores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "control_stores_controls",
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["control_id"], ["controls.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["control_stores.id"]),
        sa.PrimaryKeyConstraint("store_id", "control_id"),
    )
    op.create_index(
        "idx_control_stores_controls_store_published",
        "control_stores_controls",
        ["store_id", "published_at", "control_id"],
        unique=False,
    )
    op.create_index(
        "idx_control_stores_controls_control",
        "control_stores_controls",
        ["control_id"],
        unique=False,
    )

    op.add_column(
        "controls",
        sa.Column(
            "cloned_control_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_controls_cloned_control_id_controls",
        "controls",
        "controls",
        ["cloned_control_id"],
        ["id"],
    )

    control_stores = sa.table(
        "control_stores",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
    )
    op.get_bind().execute(
        sa.insert(control_stores).values(id=1, name="default")
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_controls_cloned_control_id_controls",
        "controls",
        type_="foreignkey",
    )
    op.drop_column("controls", "cloned_control_id")

    op.drop_index(
        "idx_control_stores_controls_control",
        table_name="control_stores_controls",
    )
    op.drop_index(
        "idx_control_stores_controls_store_published",
        table_name="control_stores_controls",
    )
    op.drop_table("control_stores_controls")
    op.drop_table("control_stores")
