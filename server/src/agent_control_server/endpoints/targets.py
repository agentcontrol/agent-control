"""REST endpoints for target management.

Surface area: targets CRUD plus attach/detach/toggle/list of controls on a
target. Runtime control resolution from targets is handled separately.

Two URL shapes exist for the attach/detach write path:

- ``/targets/{target_id}/controls/{control_id}`` — the original int-id
  routes, kept for callers that already hold an internal ``target_id``.
- ``/targets/{target_type}/{external_id}/controls/{control_id}`` — the
  natural-key routes, so client-facing consumers never need to look up
  Agent Control's internal surrogate key. These lazily create the target
  row on PUT if absent.

Tenant context is resolved via the ``get_tenant_id`` dependency, which reads
an optional ``X-Tenant-Id`` header and falls back to ``DEFAULT_TENANT_ID``
when absent, so callers that do not supply a tenant land on the default.
"""

from __future__ import annotations

from typing import Annotated

from agent_control_models import (
    AttachTargetControlRequest,
    CreateTargetRequest,
    CreateTargetResponse,
    ListTargetControlsByNaturalKeyResponse,
    ListTargetControlsResponse,
    ListTargetsResponse,
    TargetControlSummary,
    TargetSummary,
    ToggleTargetControlRequest,
)
from agent_control_models.errors import ErrorCode
from fastapi import APIRouter, Depends, Path
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..db import get_async_db
from ..errors import ConflictError, DatabaseError, NotFoundError
from ..logging_utils import get_logger
from ..models import Target
from ..services import targets as targets_service
from ..services.tenant_scoped_lookups import get_control_in_tenant_or_404
from ..tenancy import get_tenant_id

# Path-parameter charset guards. Kept in sync with ``TargetTypeStr`` and
# ``ExternalIdStr`` in agent_control_models.target. Duplicated here because
# FastAPI's Path() takes a pattern literal, not a pydantic type.
_TARGET_TYPE_PATH_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_EXTERNAL_ID_PATH_PATTERN = r"^[A-Za-z0-9._-]{1,255}$"

_TargetTypePath = Annotated[
    str,
    Path(pattern=_TARGET_TYPE_PATH_PATTERN, description="Target type slug."),
]
_ExternalIdPath = Annotated[
    str,
    Path(
        pattern=_EXTERNAL_ID_PATH_PATTERN,
        description="Caller-supplied external identifier.",
    ),
]

router = APIRouter(prefix="/targets", tags=["targets"])

_logger = get_logger(__name__)


def _to_summary(target: Target) -> TargetSummary:
    return TargetSummary(
        id=target.id,
        tenant_id=target.tenant_id,
        target_type=target.target_type,
        external_id=target.external_id,
        name=target.name,
        data=dict(target.data or {}),
        created_at=target.created_at.isoformat() if target.created_at else "",
    )


async def _get_target_or_404(
    *, tenant_id: str, target_id: int, db: AsyncSession
) -> Target:
    target = await targets_service.get_target_by_id(
        tenant_id=tenant_id, target_id=target_id, db=db
    )
    if target is None:
        raise NotFoundError(
            error_code=ErrorCode.TARGET_NOT_FOUND,
            detail=f"Target with ID '{target_id}' not found",
            resource="Target",
            resource_id=str(target_id),
            hint="Verify the target ID and tenant scope.",
        )
    return target


@router.post(
    "",
    dependencies=[Depends(require_admin_key)],
    response_model=CreateTargetResponse,
    status_code=201,
    summary="Create a target",
    response_description="Created target ID",
)
async def create_target(
    request: CreateTargetRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> CreateTargetResponse:
    """Create a new target scoped to the effective tenant.

    The combination ``(tenant_id, target_type, external_id)`` must be unique.
    """
    try:
        target = await targets_service.create_target(
            tenant_id=tenant_id,
            target_type=request.target_type,
            external_id=request.external_id,
            name=request.name,
            data=dict(request.data or {}),
            db=db,
        )
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            error_code=ErrorCode.TARGET_CONFLICT,
            detail=(
                f"Target with target_type='{request.target_type}' and "
                f"external_id='{request.external_id}' already exists in this tenant."
            ),
            resource="Target",
            resource_id=request.external_id,
            hint="Use a different external_id or update the existing target.",
        )
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to create target (type=%s, external_id=%s)",
            request.target_type,
            request.external_id,
            exc_info=True,
        )
        raise DatabaseError(
            detail="Failed to create target: database error",
            resource="Target",
            operation="create",
        )
    return CreateTargetResponse(target_id=target.id)


@router.get(
    "",
    response_model=ListTargetsResponse,
    summary="List targets visible to the current tenant",
    response_description="Targets, optionally filtered by target_type",
)
async def list_targets(
    target_type: str | None = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> ListTargetsResponse:
    """List targets for the effective tenant, optionally filtering by target_type."""
    rows = await targets_service.list_targets(
        tenant_id=tenant_id, target_type=target_type, db=db
    )
    return ListTargetsResponse(targets=[_to_summary(row) for row in rows])


@router.get(
    "/{target_id}",
    response_model=TargetSummary,
    summary="Get a target by ID",
    response_description="Target details",
)
async def get_target(
    target_id: int,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> TargetSummary:
    target = await _get_target_or_404(tenant_id=tenant_id, target_id=target_id, db=db)
    return _to_summary(target)


@router.delete(
    "/{target_id}",
    dependencies=[Depends(require_admin_key)],
    status_code=204,
    summary="Delete a target",
    response_description="Empty response on success",
)
async def delete_target(
    target_id: int,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Delete a target. Attached ``target_controls`` rows cascade automatically."""
    removed = await targets_service.delete_target(
        tenant_id=tenant_id, target_id=target_id, db=db
    )
    if not removed:
        raise NotFoundError(
            error_code=ErrorCode.TARGET_NOT_FOUND,
            detail=f"Target with ID '{target_id}' not found",
            resource="Target",
            resource_id=str(target_id),
            hint="Verify the target ID and tenant scope.",
        )


@router.post(
    "/{target_id}/controls/{control_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=TargetControlSummary,
    summary="Attach a control to a target",
    response_description="Attachment row details",
)
async def attach_target_control(
    target_id: int,
    control_id: int,
    request: AttachTargetControlRequest | None = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> TargetControlSummary:
    """Attach a control to a target idempotently. The body is optional; when
    omitted, the attachment defaults to ``enabled=true``.
    """
    await _get_target_or_404(tenant_id=tenant_id, target_id=target_id, db=db)
    if not await targets_service.control_exists_in_tenant(
        control_id=control_id, tenant_id=tenant_id, db=db
    ):
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )

    enabled = request.enabled if request is not None else True
    result = await targets_service.attach_control_to_target(
        target_id=target_id, control_id=control_id, enabled=enabled, db=db
    )
    # On a no-op (attachment already existed), return the stored state so the
    # client sees the current server-side truth rather than the request value.
    stored_enabled = enabled
    if not result.created:
        existing = await targets_service.set_target_control_enabled(
            target_id=target_id,
            control_id=control_id,
            enabled=enabled,
            db=db,
        )
        # If the attachment vanished between the two calls, surface 404.
        if existing is None:
            raise NotFoundError(
                error_code=ErrorCode.TARGET_CONTROL_NOT_FOUND,
                detail="Target control attachment disappeared during retry",
                resource="TargetControl",
                hint="Retry the request.",
            )
        stored_enabled = existing.enabled
    return TargetControlSummary(
        id=result.attachment_id, control_id=control_id, enabled=stored_enabled
    )


@router.delete(
    "/{target_id}/controls/{control_id}",
    dependencies=[Depends(require_admin_key)],
    status_code=204,
    summary="Detach a control from a target",
    response_description="Empty response on success",
)
async def detach_target_control(
    target_id: int,
    control_id: int,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Detach a control from a target. 404 if the target is out of tenant scope
    or the attachment does not exist.
    """
    await _get_target_or_404(tenant_id=tenant_id, target_id=target_id, db=db)
    removed = await targets_service.detach_control_from_target(
        target_id=target_id, control_id=control_id, db=db
    )
    if not removed:
        raise NotFoundError(
            error_code=ErrorCode.TARGET_CONTROL_NOT_FOUND,
            detail=(
                f"Control '{control_id}' is not attached to target '{target_id}'"
            ),
            resource="TargetControl",
            hint="Verify the target and control IDs.",
        )


@router.patch(
    "/{target_id}/controls/{control_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=TargetControlSummary,
    summary="Toggle a target_control attachment's enabled flag",
    response_description="Updated attachment row",
)
async def toggle_target_control(
    target_id: int,
    control_id: int,
    request: ToggleTargetControlRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> TargetControlSummary:
    """Enable or disable an existing target-control attachment."""
    await _get_target_or_404(tenant_id=tenant_id, target_id=target_id, db=db)
    attachment = await targets_service.set_target_control_enabled(
        target_id=target_id,
        control_id=control_id,
        enabled=request.enabled,
        db=db,
    )
    if attachment is None:
        raise NotFoundError(
            error_code=ErrorCode.TARGET_CONTROL_NOT_FOUND,
            detail=(
                f"Control '{control_id}' is not attached to target '{target_id}'"
            ),
            resource="TargetControl",
            hint="Attach the control to the target first.",
        )
    return TargetControlSummary(
        id=attachment.id, control_id=attachment.control_id, enabled=attachment.enabled
    )


@router.get(
    "/{target_id}/controls",
    response_model=ListTargetControlsResponse,
    summary="List controls attached to a target",
    response_description="Attachments for the target",
)
async def list_controls_for_target(
    target_id: int,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> ListTargetControlsResponse:
    """List all controls attached to a target."""
    await _get_target_or_404(tenant_id=tenant_id, target_id=target_id, db=db)
    rows = await targets_service.list_target_controls(target_id=target_id, db=db)
    return ListTargetControlsResponse(
        target_id=target_id,
        controls=[
            TargetControlSummary(id=row.id, control_id=row.control_id, enabled=row.enabled)
            for row in rows
        ],
    )


# ---------------------------------------------------------------------------
# Natural-key attach / detach / list
# ---------------------------------------------------------------------------


@router.get(
    "/{target_type}/{external_id}/controls",
    response_model=ListTargetControlsByNaturalKeyResponse,
    summary="List controls attached to a target identified by natural key",
    response_description="Attachments for the target; empty list if target absent",
)
async def list_controls_for_target_by_natural_key(
    target_type: _TargetTypePath,
    external_id: _ExternalIdPath,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> ListTargetControlsByNaturalKeyResponse:
    """List controls attached to a target addressed by natural key.

    Returns 200 with an empty ``controls`` list when the target does not
    exist in the caller's tenant. This matches desired-state semantics:
    clients rendering a controls panel for a log_stream treat "target not
    yet created" identically to "target exists but no controls attached."
    Distinguishing the two would force every caller to handle a 404 that
    carries no additional signal, given that a subsequent PUT creates
    the target lazily anyway.
    """
    target = await targets_service.get_target_by_natural_key(
        tenant_id=tenant_id,
        target_type=target_type,
        external_id=external_id,
        db=db,
    )
    if target is None:
        return ListTargetControlsByNaturalKeyResponse(
            target_type=target_type,
            external_id=external_id,
            controls=[],
        )

    rows = await targets_service.list_target_controls(target_id=target.id, db=db)
    return ListTargetControlsByNaturalKeyResponse(
        target_type=target_type,
        external_id=external_id,
        controls=[
            TargetControlSummary(id=row.id, control_id=row.control_id, enabled=row.enabled)
            for row in rows
        ],
    )


@router.put(
    "/{target_type}/{external_id}/controls/{control_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=TargetControlSummary,
    summary="Attach a control to a target identified by natural key",
    response_description="Current attachment state",
)
async def put_target_control_by_natural_key(
    target_type: _TargetTypePath,
    external_id: _ExternalIdPath,
    control_id: int,
    request: AttachTargetControlRequest | None = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> TargetControlSummary:
    """Idempotently attach a control to a target addressed by natural key.

    Desired-state semantics: the attachment converges to ``enabled``
    regardless of prior existence. If the target row does not exist yet
    in the caller's tenant, it is created lazily with empty metadata. A
    control that does not exist in the caller's tenant surfaces as 404
    with the same shape as a control that exists in another tenant, so
    cross-tenant non-disclosure is preserved.
    """
    # Control existence check is tenant-scoped, so a control belonging to
    # another tenant returns AGENT_NOT_FOUND-style 404 without leaking.
    await get_control_in_tenant_or_404(
        tenant_id=tenant_id, control_id=control_id, db=db
    )

    target, created = await targets_service.ensure_target_by_natural_key(
        tenant_id=tenant_id,
        target_type=target_type,
        external_id=external_id,
        db=db,
    )
    if created:
        _logger.info(
            "Lazily created target on natural-key attach "
            "(tenant_id=%s, target_type=%s, external_id=%s, target_id=%s)",
            tenant_id,
            target_type,
            external_id,
            target.id,
        )

    enabled = request.enabled if request is not None else True
    attachment = await targets_service.upsert_target_control_attachment(
        target_id=target.id,
        control_id=control_id,
        enabled=enabled,
        db=db,
    )
    return TargetControlSummary(
        id=attachment.id,
        control_id=attachment.control_id,
        enabled=attachment.enabled,
    )


@router.delete(
    "/{target_type}/{external_id}/controls/{control_id}",
    dependencies=[Depends(require_admin_key)],
    status_code=204,
    summary="Detach a control from a target identified by natural key",
    response_description="Empty response on success",
)
async def delete_target_control_by_natural_key(
    target_type: _TargetTypePath,
    external_id: _ExternalIdPath,
    control_id: int,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Idempotently detach a control from a target addressed by natural key.

    Final-state semantics: returns 204 whether the attachment existed and
    was removed, the attachment never existed, or the target row itself
    does not exist in the caller's tenant. A control that does not exist
    in the caller's tenant still surfaces as 404 to avoid masking caller
    errors under detach idempotency.
    """
    await get_control_in_tenant_or_404(
        tenant_id=tenant_id, control_id=control_id, db=db
    )

    target = await targets_service.get_target_by_natural_key(
        tenant_id=tenant_id,
        target_type=target_type,
        external_id=external_id,
        db=db,
    )
    if target is None:
        return

    await targets_service.detach_control_from_target(
        target_id=target.id, control_id=control_id, db=db
    )
