"""HTTP endpoints for managing the ``control_bindings`` table."""

from __future__ import annotations

from agent_control_models.errors import ErrorCode
from agent_control_models.server import (
    CreateControlBindingRequest,
    CreateControlBindingResponse,
    DeleteControlBindingByKeyRequest,
    DeleteControlBindingByKeyResponse,
    DeleteControlBindingResponse,
    GetControlBindingResponse,
    ListControlBindingsResponse,
    PaginationInfo,
    PatchControlBindingRequest,
    PatchControlBindingResponse,
    UpsertControlBindingRequest,
    UpsertControlBindingResponse,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..db import get_async_db
from ..errors import BadRequestError
from ..models import ControlBinding
from ..namespace import get_namespace_key
from ..services.control_bindings import ControlBindingsService

router = APIRouter(prefix="/control-bindings", tags=["control-bindings"])

_DEFAULT_LIST_LIMIT = 20
_MAX_LIST_LIMIT = 100


def _to_response(binding: ControlBinding) -> GetControlBindingResponse:
    return GetControlBindingResponse(
        id=binding.id,
        namespace_key=binding.namespace_key,
        target_type=binding.target_type,
        target_id=binding.target_id,
        control_id=binding.control_id,
        enabled=binding.enabled,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


@router.put(
    "",
    dependencies=[Depends(require_admin_key)],
    response_model=CreateControlBindingResponse,
    summary="Create a control binding",
    response_description="Created binding ID",
)
async def create_control_binding(
    request: CreateControlBindingRequest,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> CreateControlBindingResponse:
    """Attach a control to an opaque external target.

    Each binding row is an attachment scoped to the request's namespace; the
    ``enabled`` flag is a soft toggle. Per-agent overrides and exemptions are
    intentionally out of scope; see ``ControlBinding`` for the forward path.
    """
    service = ControlBindingsService(db)
    binding = await service.create_binding(
        namespace_key=namespace_key,
        target_type=request.target_type,
        target_id=request.target_id,
        control_id=request.control_id,
        enabled=request.enabled,
    )
    await db.commit()
    await db.refresh(binding)
    return CreateControlBindingResponse(binding_id=binding.id)


@router.get(
    "",
    response_model=ListControlBindingsResponse,
    summary="List control bindings",
    response_description="Bindings matching the supplied filters",
)
async def list_control_bindings(
    cursor: str | None = Query(
        None,
        description=(
            "Opaque cursor returned as ``next_cursor`` on the previous page. "
            "Pass it back unchanged to fetch the next page."
        ),
    ),
    limit: int = Query(
        _DEFAULT_LIST_LIMIT,
        ge=1,
        le=_MAX_LIST_LIMIT,
        description="Maximum bindings to return (default 20, max 100).",
    ),
    target_type: str | None = None,
    target_id: str | None = None,
    control_id: int | None = None,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> ListControlBindingsResponse:
    """Return bindings in the current namespace with optional filters and
    cursor-based pagination. Bindings are ordered by ID descending (newest
    first). The cursor is opaque to clients: pass back the
    ``next_cursor`` value verbatim to fetch the following page.
    """
    parsed_cursor: int | None
    if cursor is None:
        parsed_cursor = None
    else:
        try:
            parsed_cursor = int(cursor)
        except ValueError as exc:
            raise BadRequestError(
                error_code=ErrorCode.VALIDATION_ERROR,
                detail="cursor must be a value returned by next_cursor.",
                hint="Pass the cursor returned in the previous response unchanged.",
            ) from exc
    service = ControlBindingsService(db)
    page = await service.list_bindings(
        namespace_key=namespace_key,
        cursor=parsed_cursor,
        limit=limit,
        target_type=target_type,
        target_id=target_id,
        control_id=control_id,
    )
    return ListControlBindingsResponse(
        bindings=[_to_response(b) for b in page.bindings],
        pagination=PaginationInfo(
            limit=limit,
            total=page.total,
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        ),
    )


@router.get(
    "/{binding_id}",
    response_model=GetControlBindingResponse,
    summary="Get a control binding",
    response_description="The requested binding",
)
async def get_control_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> GetControlBindingResponse:
    service = ControlBindingsService(db)
    binding = await service.get_binding_or_404(namespace_key=namespace_key, binding_id=binding_id)
    return _to_response(binding)


@router.patch(
    "/{binding_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=PatchControlBindingResponse,
    summary="Update a control binding",
    response_description="Updated enabled flag",
)
async def patch_control_binding(
    binding_id: int,
    request: PatchControlBindingRequest,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> PatchControlBindingResponse:
    """Update the ``enabled`` flag on a control binding."""
    service = ControlBindingsService(db)
    binding = await service.set_enabled(
        namespace_key=namespace_key,
        binding_id=binding_id,
        enabled=request.enabled,
    )
    await db.commit()
    return PatchControlBindingResponse(success=True, enabled=binding.enabled)


@router.delete(
    "/{binding_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=DeleteControlBindingResponse,
    summary="Delete a control binding",
    response_description="Deletion confirmation",
)
async def delete_control_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> DeleteControlBindingResponse:
    service = ControlBindingsService(db)
    await service.delete_binding(namespace_key=namespace_key, binding_id=binding_id)
    await db.commit()
    return DeleteControlBindingResponse(success=True)


@router.put(
    "/by-key",
    dependencies=[Depends(require_admin_key)],
    response_model=UpsertControlBindingResponse,
    summary="Attach a control to a target by natural key (idempotent)",
    response_description="Created or updated binding",
)
async def upsert_control_binding_by_key(
    request: UpsertControlBindingRequest,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> UpsertControlBindingResponse:
    """Idempotent attach using ``(target_type, target_id, control_id)`` as the
    natural key. Updates ``enabled`` on an existing match; creates a new row
    otherwise.
    """
    service = ControlBindingsService(db)
    binding, created = await service.upsert_by_natural_key(
        namespace_key=namespace_key,
        target_type=request.target_type,
        target_id=request.target_id,
        control_id=request.control_id,
        enabled=request.enabled,
    )
    await db.commit()
    await db.refresh(binding)
    return UpsertControlBindingResponse(
        binding_id=binding.id,
        created=created,
        enabled=binding.enabled,
    )


@router.post(
    "/by-key:delete",
    dependencies=[Depends(require_admin_key)],
    response_model=DeleteControlBindingByKeyResponse,
    summary="Detach a control from a target by natural key (idempotent)",
    response_description="Whether a row was deleted",
)
async def delete_control_binding_by_key(
    request: DeleteControlBindingByKeyRequest,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> DeleteControlBindingByKeyResponse:
    """Idempotent detach by natural key. Returns ``deleted=False`` when no
    matching binding exists.
    """
    service = ControlBindingsService(db)
    deleted = await service.delete_by_natural_key(
        namespace_key=namespace_key,
        target_type=request.target_type,
        target_id=request.target_id,
        control_id=request.control_id,
    )
    await db.commit()
    return DeleteControlBindingByKeyResponse(deleted=deleted)
