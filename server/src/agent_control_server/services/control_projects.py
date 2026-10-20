"""Project lifecycle serialization shared by writes and cleanup.

Callers retain the row lock until their own transaction commits or rolls back.
Never hold this lock across a remote authorization request.
"""

from agent_control_models.errors import ErrorCode
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ConflictError
from ..models import ControlProjectScope, ControlTargetScope


async def ensure_project_scope(
    db: AsyncSession, namespace_key: str, project_id: str
) -> ControlProjectScope:
    """Create if absent and lock the durable project lifecycle row."""
    await db.execute(
        insert(ControlProjectScope)
        .values(namespace_key=namespace_key, project_id=project_id, state="active")
        .on_conflict_do_nothing(index_elements=["namespace_key", "project_id"])
    )
    result = await db.execute(
        select(ControlProjectScope)
        .where(
            ControlProjectScope.namespace_key == namespace_key,
            ControlProjectScope.project_id == project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def ensure_project_active(
    db: AsyncSession, namespace_key: str, project_id: str
) -> ControlProjectScope:
    """Reject writes after cleanup has claimed or tombstoned a project."""
    scope = await ensure_project_scope(db, namespace_key, project_id)
    if scope.state != "active":
        raise ConflictError(
            error_code=ErrorCode.CONTROL_IN_USE,
            detail="The project's control scope is being deleted or has been deleted.",
            resource="ControlProject",
            resource_id=project_id,
            hint="Do not retry writes to a deleted project.",
        )
    return scope


async def ensure_target_scope(
    db: AsyncSession, namespace_key: str, project_id: str, target_type: str, target_id: str
) -> ControlTargetScope:
    """Lock a target after its project lock; never reassign a target's project."""
    await db.execute(
        insert(ControlTargetScope)
        .values(
            namespace_key=namespace_key,
            project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            state="active",
        )
        .on_conflict_do_nothing(index_elements=["namespace_key", "target_type", "target_id"])
    )
    result = await db.execute(
        select(ControlTargetScope)
        .where(
            ControlTargetScope.namespace_key == namespace_key,
            ControlTargetScope.target_type == target_type,
            ControlTargetScope.target_id == target_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    scope = result.scalar_one()
    if scope.project_id != project_id:
        raise ConflictError(
            error_code=ErrorCode.CONTROL_IN_USE,
            detail="The target belongs to another project.",
            resource="ControlTarget",
        )
    return scope


async def ensure_target_active(
    db: AsyncSession, namespace_key: str, project_id: str, target_type: str, target_id: str
) -> ControlTargetScope:
    """Reject attachment writes after stream cleanup has claimed this target."""
    scope = await ensure_target_scope(db, namespace_key, project_id, target_type, target_id)
    if scope.state != "active":
        raise ConflictError(
            error_code=ErrorCode.CONTROL_IN_USE,
            detail="The target's control scope has been deleted.",
            resource="ControlTarget",
        )
    return scope
