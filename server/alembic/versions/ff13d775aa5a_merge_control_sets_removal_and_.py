"""Merge control_sets removal and observability schema.

Revision ID: ff13d775aa5a
Revises: a1b2c3d4e5f6, simplify_observability_schema
Create Date: 2026-01-19

This merge migration combines two parallel branches:
- a1b2c3d4e5f6: Remove control_sets layer, add policy_controls
- simplify_observability_schema: Simplified observability tables

Both branches independently modify the schema without conflicts.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ff13d775aa5a'
down_revision = ('a1b2c3d4e5f6', 'simplify_observability_schema')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
