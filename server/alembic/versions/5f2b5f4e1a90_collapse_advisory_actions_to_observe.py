"""collapse advisory actions to observe

Revision ID: 5f2b5f4e1a90
Revises: 8b23d645f86d
Create Date: 2026-04-01 17:15:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "5f2b5f4e1a90"
down_revision = "8b23d645f86d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE controls
            SET data = jsonb_set(data, '{action,decision}', '"observe"'::jsonb, false)
            WHERE jsonb_typeof(data) = 'object'
              AND jsonb_typeof(data->'action') = 'object'
              AND data->'action'->>'decision' IN ('allow', 'warn', 'log')
            """
        )
    )


def downgrade() -> None:
    raise NotImplementedError(
        "This migration is irreversible and does not reconstruct legacy advisory action names."
    )
