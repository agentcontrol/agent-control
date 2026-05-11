from agent_control_models.errors import ErrorCode
from agent_control_models.server import (
    AssocResponse,
    CreatePolicyRequest,
    CreatePolicyResponse,
    GetPolicyControlsResponse,
)
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_framework import Operation, Principal, require_operation
from ..db import get_async_db
from ..errors import ConflictError, DatabaseError, NotFoundError
from ..logging_utils import get_logger
from ..models import Policy
from ..services.controls import ControlService

router = APIRouter(prefix="/policies", tags=["policies"])

_logger = get_logger(__name__)


@router.put(
    "",
    response_model=CreatePolicyResponse,
    summary="Create a new policy",
    response_description="Created policy ID",
)
async def create_policy(
    request: CreatePolicyRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.POLICIES_CREATE)),
) -> CreatePolicyResponse:
    """
    Create a new empty policy with a unique name.

    Policies contain controls and can be assigned to agents.
    A newly created policy has no controls until they are explicitly added.

    Args:
        request: Policy creation request with unique name
        db: Database session (injected)

    Returns:
        CreatePolicyResponse with the new policy's ID

    Raises:
        HTTPException 409: Policy with this name already exists
        HTTPException 500: Database error during creation
    """
    namespace_key = principal.namespace_key
    # Uniqueness check
    existing = await db.execute(
        select(Policy.id).where(
            Policy.namespace_key == namespace_key,
            Policy.name == request.name,
        )
    )
    if existing.first() is not None:
        raise ConflictError(
            error_code=ErrorCode.POLICY_NAME_CONFLICT,
            detail=f"Policy with name '{request.name}' already exists",
            resource="Policy",
            resource_id=request.name,
            hint="Choose a different name or update the existing policy.",
        )

    policy = Policy(namespace_key=namespace_key, name=request.name)
    db.add(policy)
    try:
        await db.commit()
        await db.refresh(policy)
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to create policy '{request.name}'",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to create policy '{request.name}': database error",
            resource="Policy",
            operation="create",
        )
    return CreatePolicyResponse(policy_id=policy.id)


@router.post(
    "/{policy_id}/controls/{control_id}",
    response_model=AssocResponse,
    summary="Add control to policy",
    response_description="Success confirmation",
)
async def add_control_to_policy(
    policy_id: int,
    control_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.POLICIES_UPDATE)),
) -> AssocResponse:
    """
    Associate a control with a policy.

    This operation is idempotent - adding the same control multiple times has no effect.
    Agents with this policy will immediately see the added control.

    Args:
        policy_id: ID of the policy
        control_id: ID of the control to add
        db: Database session (injected)

    Returns:
        AssocResponse with success flag

    Raises:
        HTTPException 404: Policy or control not found
        HTTPException 500: Database error
    """
    namespace_key = principal.namespace_key
    # Find policy and control
    pol_res = await db.execute(
        select(Policy).where(
            Policy.namespace_key == namespace_key,
            Policy.id == policy_id,
        )
    )
    policy = pol_res.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(
        control_id, namespace_key=namespace_key
    )

    # Add association using INSERT ... ON CONFLICT DO NOTHING for idempotency
    try:
        await control_service.add_control_to_policy(
            policy_id=policy_id,
            control_id=control_id,
            namespace_key=namespace_key,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to add control '%s' (%s) to policy '%s' (%s)",
            control.name,
            control_id,
            policy.name,
            policy_id,
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to add control '{control.name}' to "
                f"policy '{policy.name}': database error"
            ),
            resource="Policy",
            operation="add control",
        )

    return AssocResponse(success=True)


@router.delete(
    "/{policy_id}/controls/{control_id}",
    response_model=AssocResponse,
    summary="Remove control from policy",
    response_description="Success confirmation",
)
async def remove_control_from_policy(
    policy_id: int,
    control_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.POLICIES_UPDATE)),
) -> AssocResponse:
    """
    Remove a control from a policy.

    This operation is idempotent - removing a non-associated control has no effect.
    Agents with this policy will immediately lose the removed control.

    Args:
        policy_id: ID of the policy
        control_id: ID of the control to remove
        db: Database session (injected)

    Returns:
        AssocResponse with success flag

    Raises:
        HTTPException 404: Policy or control not found
        HTTPException 500: Database error
    """
    namespace_key = principal.namespace_key
    pol_res = await db.execute(
        select(Policy).where(
            Policy.namespace_key == namespace_key,
            Policy.id == policy_id,
        )
    )
    policy = pol_res.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(
        control_id, namespace_key=namespace_key
    )

    # Remove association (idempotent - deleting non-existent is no-op)
    try:
        await control_service.remove_control_from_policy(
            policy_id=policy_id,
            control_id=control_id,
            namespace_key=namespace_key,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to remove control '{control.name}' ({control_id}) "
            f"from policy '{policy.name}' ({policy_id})",
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to remove control '{control.name}' from "
                f"policy '{policy.name}': database error"
            ),
            resource="Policy",
            operation="remove control",
        )

    return AssocResponse(success=True)


@router.get(
    "/{policy_id}/controls",
    response_model=GetPolicyControlsResponse,
    summary="List policy's controls",
    response_description="List of control IDs",
)
async def list_policy_controls(
    policy_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.POLICIES_READ)),
) -> GetPolicyControlsResponse:
    """
    List all controls associated with a policy.

    Args:
        policy_id: ID of the policy
        db: Database session (injected)

    Returns:
        GetPolicyControlsResponse with list of control IDs

    Raises:
        HTTPException 404: Policy not found
    """
    namespace_key = principal.namespace_key
    pol_res = await db.execute(
        select(Policy.id).where(
            Policy.namespace_key == namespace_key,
            Policy.id == policy_id,
        )
    )
    if pol_res.first() is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    control_ids = await ControlService(db).list_policy_control_ids(
        policy_id,
        namespace_key=namespace_key,
    )
    return GetPolicyControlsResponse(control_ids=control_ids)
