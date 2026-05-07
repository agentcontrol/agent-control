"""HTTP endpoints for managing the ``control_bindings`` table."""

from __future__ import annotations

from typing import Any

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
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_framework import Operation, Principal, require_operation
from ..db import get_async_db
from ..errors import BadRequestError
from ..models import ControlBinding
from ..services.control_bindings import ControlBindingsService

router = APIRouter(prefix="/control-bindings", tags=["control-bindings"])

_DEFAULT_LIST_LIMIT = 20
_MAX_LIST_LIMIT = 100


async def _binding_body_context(request: Request) -> dict[str, Any]:
    """Surface ``(target_type, target_id)`` to the authorization context.

    The body-bearing binding endpoints carry the target identifiers in
    the request payload. Authorization providers can use those
    identifiers when a request needs target-scoped access checks.

    FastAPI caches the parsed body, so the endpoint's own Pydantic
    request model still binds normally.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001  malformed JSON falls through to endpoint validation
        return {}
    if not isinstance(body, dict):
        return {}
    return {
        "target_type": body.get("target_type"),
        "target_id": body.get("target_id"),
    }


async def _binding_list_context(request: Request) -> dict[str, Any]:
    """Surface optional target query parameters to authorization context.

    When the GET list endpoint is called with ``target_type`` and
    ``target_id`` query params, the request is target-scoped and the
    request context includes those identifiers. When neither is present
    the request is namespace-wide and forwards no target context.
    """
    target_type = request.query_params.get("target_type")
    target_id = request.query_params.get("target_id")
    if target_type is None and target_id is None:
        return {}
    return {"target_type": target_type, "target_id": target_id}


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
    response_model=CreateControlBindingResponse,
    summary="Create a control binding",
    response_description="Created binding ID",
)
async def create_control_binding(
    request: CreateControlBindingRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(
        require_operation(
            Operation.CONTROL_BINDINGS_WRITE,
            context_builder=_binding_body_context,
        )
    ),
) -> CreateControlBindingResponse:
    """Attach a control to an opaque external target.

    Each binding row is scoped to the namespace associated with the
    authenticated request.
    """
    service = ControlBindingsService(db)
    binding = await service.create_binding(
        namespace_key=principal.namespace_key,
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
    principal: Principal = Depends(
        require_operation(
            Operation.CONTROL_BINDINGS_READ,
            context_builder=_binding_list_context,
        )
    ),
) -> ListControlBindingsResponse:
    """Return bindings in the request namespace with optional filters and
    cursor-based pagination. Bindings are ordered by ID descending
    (newest first). The cursor is opaque to clients: pass back the
    ``next_cursor`` value verbatim to fetch the following page. The
    storage namespace is resolved from the authenticated request.
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
        namespace_key=principal.namespace_key,
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
    summary="Get a control binding (namespace-wide)",
    response_description="The requested binding",
)
async def get_control_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.CONTROL_BINDINGS_READ)),
) -> GetControlBindingResponse:
    """Read a single control binding by surrogate ID.

    Authorization is namespace-wide: the binding's target identifiers
    are not available until after the row is loaded.
    Callers whose authorization model requires per-target permissions
    should use the natural-key endpoints (``PUT /by-key``,
    ``POST /by-key:delete``) and the target-filtered list endpoint, all
    of which include ``(target_type, target_id)`` in the request context.
    """
    service = ControlBindingsService(db)
    binding = await service.get_binding_or_404(
        namespace_key=principal.namespace_key, binding_id=binding_id
    )
    return _to_response(binding)


@router.patch(
    "/{binding_id}",
    response_model=PatchControlBindingResponse,
    summary="Update a control binding (namespace-wide)",
    response_description="Updated enabled flag",
)
async def patch_control_binding(
    binding_id: int,
    request: PatchControlBindingRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.CONTROL_BINDINGS_WRITE)),
) -> PatchControlBindingResponse:
    """Update the ``enabled`` flag on a control binding.

    See the GET-by-id docstring for the authorization scope: this route
    is namespace-wide because the target identifiers are not available
    before the binding is loaded. Use ``PUT /by-key`` for target-scoped
    upserts that include the target in the request context.
    """
    service = ControlBindingsService(db)
    binding = await service.set_enabled(
        namespace_key=principal.namespace_key,
        binding_id=binding_id,
        enabled=request.enabled,
    )
    await db.commit()
    return PatchControlBindingResponse(success=True, enabled=binding.enabled)


@router.delete(
    "/{binding_id}",
    response_model=DeleteControlBindingResponse,
    summary="Delete a control binding (namespace-wide)",
    response_description="Deletion confirmation",
)
async def delete_control_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.CONTROL_BINDINGS_WRITE)),
) -> DeleteControlBindingResponse:
    """Delete a control binding by surrogate ID.

    See the GET-by-id docstring for the authorization scope: this route
    is namespace-wide because the target identifiers are not available
    before the binding is loaded. Use ``POST /by-key:delete`` for
    target-scoped detach that includes the target in the request context.
    """
    service = ControlBindingsService(db)
    await service.delete_binding(namespace_key=principal.namespace_key, binding_id=binding_id)
    await db.commit()
    return DeleteControlBindingResponse(success=True)


@router.put(
    "/by-key",
    response_model=UpsertControlBindingResponse,
    summary="Attach a control to a target by natural key (idempotent)",
    response_description="Created or updated binding",
)
async def upsert_control_binding_by_key(
    request: UpsertControlBindingRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(
        require_operation(
            Operation.CONTROL_BINDINGS_WRITE,
            context_builder=_binding_body_context,
        )
    ),
) -> UpsertControlBindingResponse:
    """Idempotent attach using ``(target_type, target_id, control_id)`` as the
    natural key. Updates ``enabled`` on an existing match; creates a new row
    otherwise.
    """
    service = ControlBindingsService(db)
    binding, created = await service.upsert_by_natural_key(
        namespace_key=principal.namespace_key,
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
    response_model=DeleteControlBindingByKeyResponse,
    summary="Detach a control from a target by natural key (idempotent)",
    response_description="Whether a row was deleted",
)
async def delete_control_binding_by_key(
    request: DeleteControlBindingByKeyRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(
        require_operation(
            Operation.CONTROL_BINDINGS_WRITE,
            context_builder=_binding_body_context,
        )
    ),
) -> DeleteControlBindingByKeyResponse:
    """Idempotent detach by natural key. Returns ``deleted=False`` when no
    matching binding exists.
    """
    service = ControlBindingsService(db)
    deleted = await service.delete_by_natural_key(
        namespace_key=principal.namespace_key,
        target_type=request.target_type,
        target_id=request.target_id,
        control_id=request.control_id,
    )
    await db.commit()
    return DeleteControlBindingByKeyResponse(deleted=deleted)
