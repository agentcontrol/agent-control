"""Remove control_sets layer, add direct policy_controls relationship.

Revision ID: a1b2c3d4e5f6
Revises: 9f2c5f7a722f
Create Date: 2026-01-13

This migration simplifies the hierarchy from:
    Agent → Policy → ControlSet → Control
to:
    Agent → Policy → Control

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9f2c5f7a722f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old junction tables
    op.drop_index(op.f('ix_policy_control_sets_policy_id'), table_name='policy_control_sets')
    op.drop_index(op.f('ix_policy_control_sets_control_set_id'), table_name='policy_control_sets')
    op.drop_table('policy_control_sets')

    op.drop_index(op.f('ix_control_set_controls_control_set_id'), table_name='control_set_controls')
    op.drop_index(op.f('ix_control_set_controls_control_id'), table_name='control_set_controls')
    op.drop_table('control_set_controls')

    # Drop control_sets table
    op.drop_table('control_sets')

    # Create new policy_controls junction table (direct Policy ↔ Control relationship)
    op.create_table(
        'policy_controls',
        sa.Column('policy_id', sa.Integer(), nullable=False),
        sa.Column('control_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['control_id'], ['controls.id']),
        sa.ForeignKeyConstraint(['policy_id'], ['policies.id']),
        sa.PrimaryKeyConstraint('policy_id', 'control_id')
    )
    op.create_index(
        op.f('ix_policy_controls_control_id'),
        'policy_controls',
        ['control_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_policy_controls_policy_id'),
        'policy_controls',
        ['policy_id'],
        unique=False
    )


def downgrade() -> None:
    # Drop new table
    op.drop_index(op.f('ix_policy_controls_policy_id'), table_name='policy_controls')
    op.drop_index(op.f('ix_policy_controls_control_id'), table_name='policy_controls')
    op.drop_table('policy_controls')

    # Recreate control_sets table
    op.create_table(
        'control_sets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Recreate old junction tables
    op.create_table(
        'control_set_controls',
        sa.Column('control_set_id', sa.Integer(), nullable=False),
        sa.Column('control_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['control_id'], ['controls.id']),
        sa.ForeignKeyConstraint(['control_set_id'], ['control_sets.id']),
        sa.PrimaryKeyConstraint('control_set_id', 'control_id')
    )
    op.create_index(
        op.f('ix_control_set_controls_control_id'),
        'control_set_controls',
        ['control_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_control_set_controls_control_set_id'),
        'control_set_controls',
        ['control_set_id'],
        unique=False
    )

    op.create_table(
        'policy_control_sets',
        sa.Column('policy_id', sa.Integer(), nullable=False),
        sa.Column('control_set_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['control_set_id'], ['control_sets.id']),
        sa.ForeignKeyConstraint(['policy_id'], ['policies.id']),
        sa.PrimaryKeyConstraint('policy_id', 'control_set_id')
    )
    op.create_index(
        op.f('ix_policy_control_sets_control_set_id'),
        'policy_control_sets',
        ['control_set_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_policy_control_sets_policy_id'),
        'policy_control_sets',
        ['policy_id'],
        unique=False
    )

