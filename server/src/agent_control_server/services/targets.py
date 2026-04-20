"""Service layer for target management operations.

Responsibilities:

- Tenant-scoped CRUD on ``targets``.
- Attachment lifecycle on ``target_controls`` (attach, detach, toggle, list).
- Map domain-level outcomes (created, conflict, not_found, no_op) onto plain
  return types so endpoint handlers can choose HTTP semantics.

This layer does not resolve the request-scoped tenant itself; endpoints
inject the resolved ``tenant_id``. Runtime control resolution from
``target_controls`` is handled in a separate change.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Control, Target, TargetControl


@dataclass(frozen=True)
class AttachResult:
    """Outcome of attaching a control to a target."""

    attachment_id: int
    created: bool


async def get_target_by_id(
    *, tenant_id: str, target_id: int, db: AsyncSession
) -> Target | None:
    """Return the target row if it exists and belongs to the given tenant."""
    stmt = select(Target).where(Target.id == target_id, Target.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def list_targets(
    *,
    tenant_id: str,
    target_type: str | None,
    db: AsyncSession,
) -> Sequence[Target]:
    """List targets for the tenant, optionally filtered by target_type."""
    stmt = select(Target).where(Target.tenant_id == tenant_id)
    if target_type is not None:
        stmt = stmt.where(Target.target_type == target_type)
    stmt = stmt.order_by(Target.id.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def create_target(
    *,
    tenant_id: str,
    target_type: str,
    external_id: str,
    name: str | None,
    data: dict[str, Any],
    db: AsyncSession,
) -> Target:
    """Create a new target. Raises IntegrityError on uniqueness violation."""
    target = Target(
        tenant_id=tenant_id,
        target_type=target_type,
        external_id=external_id,
        name=name,
        data=data,
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)
    return target


async def delete_target(
    *, tenant_id: str, target_id: int, db: AsyncSession
) -> bool:
    """Delete a target scoped to the tenant. Returns True if a row was removed."""
    stmt = (
        delete(Target)
        .where(Target.id == target_id, Target.tenant_id == tenant_id)
        .returning(Target.id)
    )
    result = await db.execute(stmt)
    removed = result.first() is not None
    await db.commit()
    return removed


async def attach_control_to_target(
    *,
    target_id: int,
    control_id: int,
    enabled: bool,
    db: AsyncSession,
) -> AttachResult:
    """Idempotently attach a control to a target.

    Returns the attachment ID and whether the row was newly created. A second
    call with the same target/control pair is a no-op and returns ``created``
    as ``False`` without mutating the ``enabled`` flag; use the toggle
    operation to change it.
    """
    stmt = (
        pg_insert(TargetControl)
        .values(target_id=target_id, control_id=control_id, enabled=enabled)
        .on_conflict_do_nothing(index_elements=["target_id", "control_id"])
        .returning(TargetControl.id)
    )
    result = await db.execute(stmt)
    inserted_id = result.scalar_one_or_none()
    if inserted_id is not None:
        await db.commit()
        return AttachResult(attachment_id=inserted_id, created=True)

    # Row already existed; look it up to return the stable attachment_id.
    await db.commit()
    existing_stmt = select(TargetControl.id).where(
        TargetControl.target_id == target_id,
        TargetControl.control_id == control_id,
    )
    existing_id = (await db.execute(existing_stmt)).scalar_one()
    return AttachResult(attachment_id=existing_id, created=False)


async def detach_control_from_target(
    *,
    target_id: int,
    control_id: int,
    db: AsyncSession,
) -> bool:
    """Detach a control from a target. Returns True if a row was removed."""
    stmt = (
        delete(TargetControl)
        .where(
            TargetControl.target_id == target_id,
            TargetControl.control_id == control_id,
        )
        .returning(TargetControl.id)
    )
    result = await db.execute(stmt)
    removed = result.first() is not None
    await db.commit()
    return removed


async def set_target_control_enabled(
    *,
    target_id: int,
    control_id: int,
    enabled: bool,
    db: AsyncSession,
) -> TargetControl | None:
    """Set the enabled flag on an existing attachment. Returns the row or None."""
    stmt = select(TargetControl).where(
        TargetControl.target_id == target_id,
        TargetControl.control_id == control_id,
    )
    result = await db.execute(stmt)
    attachment = result.scalars().first()
    if attachment is None:
        return None
    attachment.enabled = enabled
    await db.commit()
    await db.refresh(attachment)
    return attachment


async def list_target_controls(
    *, target_id: int, db: AsyncSession
) -> Sequence[TargetControl]:
    """List attachments for a target, ordered by creation."""
    stmt = (
        select(TargetControl)
        .where(TargetControl.target_id == target_id)
        .order_by(TargetControl.id.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def control_exists_in_tenant(
    *, control_id: int, tenant_id: str, db: AsyncSession
) -> bool:
    """Return whether a control with the given ID exists in the given tenant."""
    result = await db.execute(
        select(Control.id).where(
            Control.id == control_id, Control.tenant_id == tenant_id
        )
    )
    return result.first() is not None


__all__ = [
    "AttachResult",
    "attach_control_to_target",
    "control_exists_in_tenant",
    "create_target",
    "delete_target",
    "detach_control_from_target",
    "get_target_by_id",
    "list_target_controls",
    "list_targets",
    "set_target_control_enabled",
    "IntegrityError",
]
