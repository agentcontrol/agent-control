"""HTTP endpoints for managing the ``control_bindings`` table."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
    PatchControlBindingByKeyRequest,
    PatchControlBindingRequest,
    PatchControlBindingResponse,
    UpsertControlBindingRequest,
    UpsertControlBindingResponse,
)
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_framework import Operation, Principal, get_authorizer, require_operation
from ..auth_framework.core import IdentityResolver
from ..db import AsyncSessionLocal, get_async_db
from ..errors import BadRequestError, ForbiddenError, NotFoundError
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


def _require_binding_operation(
    operation: Operation,
) -> Callable[..., Awaitable[Principal]]:
    """Use stored-target authorization when the provider opts in."""

    async def dependency(request: Request, binding_id: int) -> Principal:
        authorizer = get_authorizer(operation)
        if (
            not isinstance(authorizer, IdentityResolver)
            or not authorizer.binding_target_authorization
        ):
            # Preserve the existing single namespace-wide authorization call
            # for providers without an independent identity lookup. Their
            # operation contract may reject a new target context altogether.
            return await authorizer.authorize(request, operation)

        identity = await authorizer.resolve_identity(request, operation)
        # Use a short-lived session so no database connection is held while the
        # authorization provider performs a potentially remote request.
        async with AsyncSessionLocal() as db:
            target_type, target_id = await ControlBindingsService(
                db
            ).get_binding_target_for_authorization_or_404(
                namespace_key=identity.namespace_key, binding_id=binding_id
            )

        context = {"target_type": target_type, "target_id": target_id}
        try:
            principal = await authorizer.authorize(request, operation, context)
        except (ForbiddenError, NotFoundError) as exc:
            # A caller cannot distinguish a binding it cannot access from a
            # missing binding in its namespace.
            raise ControlBindingsService.binding_not_found(binding_id) from exc
        if principal.namespace_key != identity.namespace_key:
            # The target grant must apply to the namespace used for the lookup.
            raise ControlBindingsService.binding_not_found(binding_id)
        return principal

    return dependency


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
    summary="Get a control binding",
    response_description="The requested binding",
)
async def get_control_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(_require_binding_operation(Operation.CONTROL_BINDINGS_READ)),
) -> GetControlBindingResponse:
    """Read a single control binding by surrogate ID.

    Target-aware authorizers use the binding's stored target identifiers.
    Other authorizers retain namespace-wide authorization. The row is loaded
    using the authorized namespace before any binding data is returned.
    """
    service = ControlBindingsService(db)
    binding = await service.get_binding_or_404(
        namespace_key=principal.namespace_key, binding_id=binding_id
    )
    return _to_response(binding)


@router.patch(
    "/by-key",
    response_model=PatchControlBindingResponse,
    summary="Update a control binding by natural key",
    response_description="Updated enabled flag",
)
async def patch_control_binding_by_key(
    request: PatchControlBindingByKeyRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(
        require_operation(
            Operation.CONTROL_BINDINGS_WRITE,
            context_builder=_binding_body_context,
        )
    ),
) -> PatchControlBindingResponse:
    """Update an existing binding using ``(target_type, target_id, control_id)``.

    This route is target-scoped because the request body includes the target
    identifiers before authorization runs. Unlike ``PUT /by-key``, it never
    creates a missing binding.
    """
    service = ControlBindingsService(db)
    binding = await service.set_enabled_by_natural_key(
        namespace_key=principal.namespace_key,
        target_type=request.target_type,
        target_id=request.target_id,
        control_id=request.control_id,
        enabled=request.enabled,
    )
    await db.commit()
    return PatchControlBindingResponse(success=True, enabled=binding.enabled)


@router.patch(
    "/{binding_id}",
    response_model=PatchControlBindingResponse,
    summary="Update a control binding",
    response_description="Updated enabled flag",
)
async def patch_control_binding(
    binding_id: int,
    request: PatchControlBindingRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(_require_binding_operation(Operation.CONTROL_BINDINGS_WRITE)),
) -> PatchControlBindingResponse:
    """Update the ``enabled`` flag on a control binding.

    Target-aware authorizers use the binding's stored target identifiers.
    Other authorizers retain namespace-wide authorization. The mutation
    remains scoped to the authorized namespace.
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
    summary="Delete a control binding",
    response_description="Deletion confirmation",
)
async def delete_control_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(_require_binding_operation(Operation.CONTROL_BINDINGS_WRITE)),
) -> DeleteControlBindingResponse:
    """Delete a control binding by surrogate ID.

    Target-aware authorizers use the binding's stored target identifiers.
    Other authorizers retain namespace-wide authorization. The deletion
    remains scoped to the authorized namespace.
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
