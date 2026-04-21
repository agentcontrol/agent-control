"""Add CHECK constraints for target_type and external_id charset.

Locks in the path-safe identifier contract at the database layer so a
bypass of the Pydantic model layer (direct psycopg, migrations, etc.)
cannot smuggle values that would break natural-key URL routing.

Constraints:

- ``targets.target_type`` matches ``^[a-z][a-z0-9_]{0,63}$`` (controlled
  slug: lowercase letters, digits, underscores; starts with a letter).
- ``targets.external_id`` matches ``^[A-Za-z0-9._-]{1,255}$`` (URL-safe
  unreserved charset minus tilde).

The ``targets`` table was introduced in revision ``7c1a9b4e2d30``. Because
that migration is only days old and rows created before this constraint
are unlikely to exist outside fresh dev environments, we do not backfill
or normalize existing data. If the constraint creation fails on a legacy
row, that row should be reviewed and either deleted or updated by hand —
silent normalization risks altering caller-meaningful identifiers.

Revision ID: a3e7b2f1c4d5
Revises: 7c1a9b4e2d30
Create Date: 2026-04-21 00:00:00.000000
"""
from alembic import op


revision = "a3e7b2f1c4d5"
down_revision = "7c1a9b4e2d30"
branch_labels = None
depends_on = None


_TARGET_TYPE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9._-]{1,255}$"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_targets_target_type_charset",
        "targets",
        f"target_type ~ '{_TARGET_TYPE_PATTERN}'",
    )
    op.create_check_constraint(
        "ck_targets_external_id_charset",
        "targets",
        f"external_id ~ '{_EXTERNAL_ID_PATTERN}'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_targets_external_id_charset", "targets", type_="check"
    )
    op.drop_constraint(
        "ck_targets_target_type_charset", "targets", type_="check"
    )
