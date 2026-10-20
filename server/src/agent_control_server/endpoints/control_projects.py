"""Ownership-aware cleanup before an upstream project disappears."""

from agent_control_models.control_projects import (
    CleanupProjectControlsRequest,
    CleanupProjectControlsResponse,
)
from agent_control_models.errors import ErrorCode
from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_framework import Operation, get_authorizer
from ..db import get_async_db
from ..errors import ForbiddenError
from ..services.control_project_cleanup import (
    cleanup_project_controls,
    detach_project_target,
)

router = APIRouter(prefix="/control-projects", tags=["control-projects"])


@router.post("/{project_id}:cleanup", response_model=CleanupProjectControlsResponse)
async def cleanup_project(
    request: CleanupProjectControlsRequest,
    http_request: Request,
    project_id: str = Path(min_length=1, max_length=255),
    db: AsyncSession = Depends(get_async_db),
) -> CleanupProjectControlsResponse:
    """Clean the authorized project's definitions without deleting global sources."""
    principal = await get_authorizer(Operation.PROJECT_CONTROLS_CLEANUP).authorize(
        http_request,
        Operation.PROJECT_CONTROLS_CLEANUP,
        {"project_id": project_id},
    )
    if principal.project_id != project_id:
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="Project cleanup requires a matching project grant.",
        )

    for target_id in set(request.target_ids):
        grant = await get_authorizer(Operation.CONTROL_BINDINGS_WRITE).authorize(
            http_request,
            Operation.CONTROL_BINDINGS_WRITE,
            {"target_type": "log_stream", "target_id": target_id},
        )
        if (
            grant.namespace_key != principal.namespace_key
            or grant.project_id != project_id
        ):
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="Cleanup target does not belong to the project.",
            )

    result = await cleanup_project_controls(
        db,
        namespace_key=principal.namespace_key,
        project_id=project_id,
        target_ids=list(set(request.target_ids)),
    )
    await db.commit()
    return result


@router.post(
    "/{project_id}/targets/{target_id}:detach",
    response_model=CleanupProjectControlsResponse,
)
async def detach_deleted_stream(
    http_request: Request,
    project_id: str = Path(min_length=1, max_length=255),
    target_id: str = Path(min_length=1, max_length=255),
    db: AsyncSession = Depends(get_async_db),
) -> CleanupProjectControlsResponse:
    """Detach a stream being deleted while retaining project control definitions."""
    principal = await get_authorizer(Operation.CONTROL_BINDINGS_CLEANUP).authorize(
        http_request,
        Operation.CONTROL_BINDINGS_CLEANUP,
        {"target_type": "log_stream", "target_id": target_id},
    )
    if principal.project_id != project_id:
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="Cleanup target does not belong to the project.",
        )
    result = await detach_project_target(
        db,
        namespace_key=principal.namespace_key,
        project_id=project_id,
        target_id=target_id,
    )
    await db.commit()
    return result
