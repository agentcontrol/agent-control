"""Stored-owner authorization; project ownership is never a browser filter."""

from collections.abc import Awaitable, Callable

from agent_control_models.errors import ErrorCode
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_framework import Operation, Principal, get_authorizer
from ..auth_framework.core import IdentityResolver
from ..db import get_async_db
from ..errors import ForbiddenError, NotFoundError
from .controls import ControlService

PROJECT_OPERATIONS = {
    Operation.CONTROLS_READ: Operation.PROJECT_CONTROLS_READ,
    Operation.CONTROLS_CREATE: Operation.PROJECT_CONTROLS_CREATE,
    Operation.CONTROLS_UPDATE: Operation.PROJECT_CONTROLS_UPDATE,
    Operation.CONTROLS_DELETE: Operation.PROJECT_CONTROLS_DELETE,
}


async def authorize_owner(
    request: Request, operation: Operation, project_id: str | None
) -> Principal:
    """Authorize either the unchanged organization action or a project action."""
    if project_id is None:
        return await get_authorizer(operation).authorize(request, operation)
    project_operation = PROJECT_OPERATIONS[operation]
    authorizer = get_authorizer(project_operation)
    if not getattr(authorizer, "project_control_authorization", False):
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="This authorization provider does not support project-owned controls.",
            hint="Configure an ownership-aware upstream before using project ownership.",
        )
    principal = await authorizer.authorize(request, project_operation, {"project_id": project_id})
    if principal.project_id != project_id:
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="Project authorization returned a different or missing project.",
        )
    return principal


async def requested_owner(request: Request) -> str | None:
    """Read only the optional owner, leaving full body validation to FastAPI."""
    try:
        body = await request.json()
    except ValueError:
        return None
    value = body.get("owner_project_id") if isinstance(body, dict) else None
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 255:
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="A project owner must be a non-empty project identifier.",
        )
    return value.strip()


async def require_control_create(request: Request) -> Principal:
    return await authorize_owner(request, Operation.CONTROLS_CREATE, await requested_owner(request))


def require_control_operation(operation: Operation) -> Callable[..., Awaitable[Principal]]:
    """Resolve namespace, read immutable stored owner, then authorize that owner.

    The lookup transaction releases its connection before remote authorization. Unsupported
    providers retain existing organization behavior but cannot grant project access.
    """

    async def dependency(
        request: Request, control_id: int, db: AsyncSession = Depends(get_async_db)
    ) -> Principal:
        authorizer = get_authorizer(operation)
        resolved = (
            isinstance(authorizer, IdentityResolver) and authorizer.binding_target_authorization
        )
        if isinstance(authorizer, IdentityResolver) and authorizer.binding_target_authorization:
            identity = await authorizer.resolve_identity(request, operation)
        else:
            identity = await authorizer.authorize(request, operation)
        control = await ControlService(db).get_control_or_404(
            control_id, namespace_key=identity.namespace_key
        )
        owner = control.owner_project_id
        # Only a namespace/owner read happened. Return the connection before
        # remote I/O, while honoring the same injectable DB as the endpoint.
        await db.rollback()
        try:
            principal = (
                await authorize_owner(request, operation, owner)
                if resolved or owner is not None
                else identity
            )
        except (ForbiddenError, NotFoundError) as exc:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_NOT_FOUND,
                detail="Control not found.",
                resource="Control",
                resource_id=str(control_id),
            ) from exc
        if principal.namespace_key != identity.namespace_key:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_NOT_FOUND,
                detail="Control not found.",
                resource="Control",
            )
        return principal

    return dependency
