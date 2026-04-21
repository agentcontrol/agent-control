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


async def get_target_by_natural_key(
    *,
    tenant_id: str,
    target_type: str,
    external_id: str,
    db: AsyncSession,
) -> Target | None:
    """Return the target identified by ``(tenant_id, target_type, external_id)``.

    Raw lookup — no ``404`` semantics baked in because callers differ on the
    absent-row behavior: GET wants 404, PUT attach wants to lazy-create, and
    DELETE wants a 204. Keeping this helper contract-free lets each endpoint
    pick its own policy.
    """
    stmt = select(Target).where(
        Target.tenant_id == tenant_id,
        Target.target_type == target_type,
        Target.external_id == external_id,
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def ensure_target_by_natural_key(
    *,
    tenant_id: str,
    target_type: str,
    external_id: str,
    db: AsyncSession,
) -> tuple[Target, bool]:
    """Return the target for ``(tenant_id, target_type, external_id)``, creating it if absent.

    Race-safe: uses ``INSERT ... ON CONFLICT DO NOTHING`` followed by a
    re-select so two concurrent callers both end up holding the same row
    without surfacing an ``IntegrityError``.

    Returns ``(target, created)`` where ``created`` is ``True`` only when
    the insert actually produced a new row (the caller that won the race).
    Losing callers see ``created=False`` and the winner's row.
    """
    insert_stmt = (
        pg_insert(Target)
        .values(
            tenant_id=tenant_id,
            target_type=target_type,
            external_id=external_id,
            name=None,
            data={},
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "target_type", "external_id"]
        )
        .returning(Target.id)
    )
    insert_result = await db.execute(insert_stmt)
    inserted_id = insert_result.scalar_one_or_none()
    await db.commit()

    select_stmt = select(Target).where(
        Target.tenant_id == tenant_id,
        Target.target_type == target_type,
        Target.external_id == external_id,
    )
    select_result = await db.execute(select_stmt)
    target = select_result.scalars().first()
    if target is None:
        # Should be unreachable: either we just inserted or another writer
        # did, so the row must exist by the time we select. Guarded for
        # readability of the tuple return contract.
        raise RuntimeError(
            "ensure_target_by_natural_key: row vanished between insert and select"
        )
    return target, inserted_id is not None


async def upsert_target_control_attachment(
    *,
    target_id: int,
    control_id: int,
    enabled: bool,
    db: AsyncSession,
) -> TargetControl:
    """Create or update the ``(target, control)`` attachment to the desired state.

    Race-safe: ``INSERT ... ON CONFLICT DO UPDATE SET enabled = EXCLUDED.enabled``
    makes the attachment converge to ``enabled`` regardless of whether it
    previously existed. This is the natural-key PUT's desired-state
    contract; concurrent PUTs with the same ``enabled`` value are no-ops,
    and competing values follow last-write-wins at the DB level.
    """
    stmt = (
        pg_insert(TargetControl)
        .values(target_id=target_id, control_id=control_id, enabled=enabled)
        .on_conflict_do_update(
            index_elements=["target_id", "control_id"],
            set_={"enabled": enabled},
        )
        .returning(
            TargetControl.id, TargetControl.control_id, TargetControl.enabled
        )
    )
    result = await db.execute(stmt)
    row = result.one()
    await db.commit()
    # Build a detached TargetControl for the return shape. We only need
    # id/control_id/enabled at the call site; full ORM hydration isn't
    # necessary here.
    attachment = TargetControl(
        id=row.id,
        target_id=target_id,
        control_id=row.control_id,
        enabled=row.enabled,
    )
    return attachment


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
    "ensure_target_by_natural_key",
    "get_target_by_id",
    "get_target_by_natural_key",
    "list_target_controls",
    "list_targets",
    "set_target_control_enabled",
    "upsert_target_control_attachment",
    "IntegrityError",
]
