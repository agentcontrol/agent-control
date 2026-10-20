"""Transactional cleanup selected by stored project ownership."""

import datetime as dt

from agent_control_models.control_projects import CleanupProjectControlsResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ..models import Control, ControlBinding, ControlTargetScope
from .control_projects import (
    ensure_project_active,
    ensure_project_scope,
    ensure_target_scope,
)
from .controls import ControlService


async def cleanup_project_controls(
    db: AsyncSession,
    *,
    namespace_key: str,
    project_id: str,
    target_ids: list[str],
) -> CleanupProjectControlsResponse:
    """Clean only the authorized owner's definitions and target bindings.

    The caller must authorize the project and every target before entering this
    transaction. The scope lock is shared with creation and binding writes.
    The caller owns commit or rollback.
    """
    scope = await ensure_project_scope(db, namespace_key, project_id)
    scope.state = "deleting"

    owned_ids = select(Control.id).where(
        Control.namespace_key == namespace_key,
        Control.owner_project_id == project_id,
    )
    # Stored target ownership is recorded only after a trusted upstream grant.
    # Include it even if Orbit's earlier stream enumeration missed a concurrent
    # stream creation. All binding writers share the project lock held above.
    recorded_targets = select(ControlTargetScope.target_id).where(
        ControlTargetScope.namespace_key == namespace_key,
        ControlTargetScope.project_id == project_id,
    )
    binding_filter: ColumnElement[bool] = or_(
        ControlBinding.control_id.in_(owned_ids),
        ControlBinding.target_type.in_(("log_stream", "agent_stream"))
        & ControlBinding.target_id.in_(recorded_targets),
    )
    if target_ids:
        binding_filter = or_(
            binding_filter,
            ControlBinding.target_type.in_(("log_stream", "agent_stream"))
            & ControlBinding.target_id.in_(target_ids),
        )
    deleted_bindings = await db.execute(
        delete(ControlBinding)
        .where(ControlBinding.namespace_key == namespace_key, binding_filter)
        .returning(ControlBinding.id)
    )
    binding_count = len(deleted_bindings.scalars().all())

    result = await db.execute(
        select(Control)
        .where(
            Control.namespace_key == namespace_key,
            Control.owner_project_id == project_id,
            Control.deleted_at.is_(None),
        )
        .order_by(Control.id)
        .with_for_update()
    )
    controls = list(result.scalars().all())
    service = ControlService(db)
    deleted_at = dt.datetime.now(dt.UTC)
    for control in controls:
        await service.remove_all_control_associations(control.id, namespace_key=namespace_key)
        service.mark_control_deleted(control, deleted_at=deleted_at)
        await service.create_version(control, event_type="deleted", note="Owning project deleted")
    scope.state = "deleted"
    await db.flush()
    return CleanupProjectControlsResponse(
        owner_project_id=project_id,
        controls_deleted=len(controls),
        bindings_deleted=binding_count,
    )


async def detach_project_target(
    db: AsyncSession,
    *,
    namespace_key: str,
    project_id: str,
    target_id: str,
) -> CleanupProjectControlsResponse:
    """Tombstone a deleted stream and detach it without deleting definitions."""
    await ensure_project_active(db, namespace_key, project_id)
    for target_type in ("agent_stream", "log_stream"):
        target = await ensure_target_scope(db, namespace_key, project_id, target_type, target_id)
        target.state = "deleted"
    result = await db.execute(
        delete(ControlBinding)
        .where(
            ControlBinding.namespace_key == namespace_key,
            ControlBinding.target_type.in_(("agent_stream", "log_stream")),
            ControlBinding.target_id == target_id,
        )
        .returning(ControlBinding.id)
    )
    return CleanupProjectControlsResponse(
        owner_project_id=project_id,
        controls_deleted=0,
        bindings_deleted=len(result.scalars().all()),
    )
