"""HTTP endpoints for managing the ``control_bindings`` table."""

from __future__ import annotations

from agent_control_models.server import (
    CreateControlBindingRequest,
    CreateControlBindingResponse,
    DeleteControlBindingResponse,
    GetControlBindingResponse,
    ListControlBindingsResponse,
    PatchControlBindingRequest,
    PatchControlBindingResponse,
)
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..db import get_async_db
from ..models import ControlBinding
from ..namespace import get_namespace_key
from ..services.control_bindings import ControlBindingsService

router = APIRouter(prefix="/control-bindings", tags=["control-bindings"])


def _to_response(binding: ControlBinding) -> GetControlBindingResponse:
    return GetControlBindingResponse(
        id=binding.id,
        namespace_key=binding.namespace_key,
        target_type=binding.target_type,
        target_id=binding.target_id,
        agent_name=binding.agent_name,
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

    Two binding shapes are supported:

    - target-default: ``agent_name`` omitted; applies to all agents that
      reference the target at runtime.
    - target-agent: ``agent_name`` set; narrows the attachment to one agent
      within the target, or exempts that agent via ``enabled = false``.
    """
    service = ControlBindingsService(db)
    binding = await service.create_binding(
        namespace_key=namespace_key,
        target_type=request.target_type,
        target_id=request.target_id,
        agent_name=request.agent_name,
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
    target_type: str | None = None,
    target_id: str | None = None,
    agent_name: str | None = None,
    control_id: int | None = None,
    db: AsyncSession = Depends(get_async_db),
    namespace_key: str = Depends(get_namespace_key),
) -> ListControlBindingsResponse:
    """Return bindings in the current namespace with optional filters."""
    service = ControlBindingsService(db)
    bindings = await service.list_bindings(
        namespace_key=namespace_key,
        target_type=target_type,
        target_id=target_id,
        agent_name=agent_name,
        control_id=control_id,
    )
    return ListControlBindingsResponse(
        bindings=[_to_response(b) for b in bindings]
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
    binding = await service.get_binding_or_404(
        namespace_key=namespace_key, binding_id=binding_id
    )
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
    await service.delete_binding(
        namespace_key=namespace_key, binding_id=binding_id
    )
    await db.commit()
    return DeleteControlBindingResponse(success=True)
