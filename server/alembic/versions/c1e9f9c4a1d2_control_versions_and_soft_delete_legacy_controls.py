"""add control versions and soft-delete unusable legacy controls

Revision ID: c1e9f9c4a1d2
Revises: 5f2b5f4e1a90
Create Date: 2026-04-15 12:00:00.000000

"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import sqlalchemy as sa
from alembic import op
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from agent_control_models import ControlDefinition, UnrenderedTemplateControl

# revision identifiers, used by Alembic.
revision = "c1e9f9c4a1d2"
down_revision = "5f2b5f4e1a90"
branch_labels = None
depends_on = None

_logger = logging.getLogger("alembic.runtime.migration")

_BACKFILL_NOTE = "Backfilled from existing control"


def _classify_control_payload(data: Any) -> tuple[bool, str | None]:
    """Return whether a legacy control payload is still usable."""
    if data == {}:
        return False, "empty payload"
    if not isinstance(data, dict):
        return False, "invalid control payload"

    try:
        UnrenderedTemplateControl.model_validate(data)
    except ValidationError:
        pass
    else:
        return True, None

    try:
        ControlDefinition.model_validate(data)
    except ValidationError:
        return False, "invalid control payload"

    return True, None


def _snapshot_payload(
    *,
    name: str,
    data: Any,
    deleted_at: dt.datetime | None,
) -> dict[str, Any]:
    """Build the JSON snapshot persisted in control_versions."""
    return {
        "name": name,
        "data": data,
        "deleted_at": deleted_at.isoformat() if deleted_at is not None else None,
        "cloned_control_id": None,
    }


def upgrade() -> None:
    op.add_column("controls", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("controls_name_key", "controls", type_="unique")
    op.create_index(
        "idx_controls_name_active",
        "controls",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "control_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column("version_num", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["control_id"], ["controls.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "control_id",
            "version_num",
            name="uq_control_versions_control_version",
        ),
    )
    op.create_index(
        "idx_control_versions_control_created",
        "control_versions",
        ["control_id", sa.literal_column("created_at DESC")],
        unique=False,
    )

    bind = op.get_bind()
    db_inspector = inspect(bind)

    controls = sa.table(
        "controls",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("data", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    control_versions = sa.table(
        "control_versions",
        sa.column("control_id", sa.Integer()),
        sa.column("version_num", sa.Integer()),
        sa.column("event_type", sa.String()),
        sa.column("snapshot", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("note", sa.Text()),
    )
    policy_controls = sa.table(
        "policy_controls",
        sa.column("policy_id", sa.Integer()),
        sa.column("control_id", sa.Integer()),
    )
    agent_controls = sa.table(
        "agent_controls",
        sa.column("agent_name", sa.String()),
        sa.column("control_id", sa.Integer()),
    )

    store_publications = None
    if db_inspector.has_table("control_stores_controls"):
        store_publications = sa.table(
            "control_stores_controls",
            sa.column("store_id", sa.Integer()),
            sa.column("control_id", sa.Integer()),
        )

    rows = bind.execute(
        sa.select(
            controls.c.id,
            controls.c.name,
            controls.c.data,
        ).order_by(controls.c.id)
    ).mappings()

    auto_deleted_controls: list[str] = []
    for row in rows:
        control_id = int(row["id"])
        control_name = str(row["name"])
        control_data = row["data"]
        usable, reason = _classify_control_payload(control_data)

        bind.execute(
            sa.insert(control_versions).values(
                control_id=control_id,
                version_num=1,
                event_type="migration_backfill",
                snapshot=_snapshot_payload(
                    name=control_name,
                    data=control_data,
                    deleted_at=None,
                ),
                note=_BACKFILL_NOTE,
            )
        )

        if usable:
            continue

        if store_publications is not None:
            bind.execute(
                sa.delete(store_publications).where(
                    store_publications.c.control_id == control_id
                )
            )
        bind.execute(
            sa.delete(policy_controls).where(policy_controls.c.control_id == control_id)
        )
        bind.execute(
            sa.delete(agent_controls).where(agent_controls.c.control_id == control_id)
        )

        deleted_at = dt.datetime.now(dt.UTC)
        bind.execute(
            sa.update(controls)
            .where(controls.c.id == control_id)
            .values(deleted_at=deleted_at)
        )
        bind.execute(
            sa.insert(control_versions).values(
                control_id=control_id,
                version_num=2,
                event_type="migration_autodelete",
                snapshot=_snapshot_payload(
                    name=control_name,
                    data=control_data,
                    deleted_at=deleted_at,
                ),
                note=f"Auto-soft-deleted during migration: {reason}",
            )
        )
        auto_deleted_controls.append(f"{control_id}:{control_name}")

    if auto_deleted_controls:
        _logger.warning(
            "Auto-soft-deleted %d unusable controls during migration: %s",
            len(auto_deleted_controls),
            ", ".join(auto_deleted_controls),
        )


def downgrade() -> None:
    op.drop_index("idx_control_versions_control_created", table_name="control_versions")
    op.drop_table("control_versions")
    op.drop_index("idx_controls_name_active", table_name="controls")
    op.create_unique_constraint("controls_name_key", "controls", ["name"])
    op.drop_column("controls", "deleted_at")
