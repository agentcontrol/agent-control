from agent_control_models.server import (
    AssocResponse,
    CreatePolicyRequest,
    CreatePolicyResponse,
    GetPolicyControlsResponse,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..logging_utils import get_logger
from ..models import Control, Policy, policy_controls

router = APIRouter(prefix="/policies", tags=["policies"])

_logger = get_logger(__name__)


@router.put(
    "",
    response_model=CreatePolicyResponse,
    summary="Create a new policy",
    response_description="Created policy ID",
)
async def create_policy(
    request: CreatePolicyRequest, db: AsyncSession = Depends(get_async_db)
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
    # Uniqueness check
    existing = await db.execute(select(Policy.id).where(Policy.name == request.name))
    if existing.first() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Policy with name '{request.name}' already exists",
        )

    policy = Policy(name=request.name)
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
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create policy '{request.name}': database error",
        )
    return CreatePolicyResponse(policy_id=policy.id)


@router.post(
    "/{policy_id}/controls/{control_id}",
    response_model=AssocResponse,
    summary="Add control to policy",
    response_description="Success confirmation",
)
async def add_control_to_policy(
    policy_id: int, control_id: int, db: AsyncSession = Depends(get_async_db)
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
    # Find policy and control
    pol_res = await db.execute(select(Policy).where(Policy.id == policy_id))
    policy = pol_res.scalars().first()
    if policy is None:
        raise HTTPException(
            status_code=404, detail=f"Policy with ID '{policy_id}' not found"
        )

    ctl_res = await db.execute(select(Control).where(Control.id == control_id))
    control = ctl_res.scalars().first()
    if control is None:
        raise HTTPException(
            status_code=404, detail=f"Control with ID '{control_id}' not found"
        )

    # Add association using INSERT ... ON CONFLICT DO NOTHING for idempotency
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(policy_controls)
            .values(policy_id=policy_id, control_id=control_id)
            .on_conflict_do_nothing()
        )
        await db.execute(stmt)
        await db.commit()
    except Exception as e:
        await db.rollback()
        _logger.error(
            f"Failed to add control '{control.name}' ({control_id}) "
            f"to policy '{policy.name}' ({policy_id}): {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to add control '{control.name}' to policy '{policy.name}': "
                f"database error"
            ),
        )

    return AssocResponse(success=True)


@router.delete(
    "/{policy_id}/controls/{control_id}",
    response_model=AssocResponse,
    summary="Remove control from policy",
    response_description="Success confirmation",
)
async def remove_control_from_policy(
    policy_id: int, control_id: int, db: AsyncSession = Depends(get_async_db)
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
    pol_res = await db.execute(select(Policy).where(Policy.id == policy_id))
    policy = pol_res.scalars().first()
    if policy is None:
        raise HTTPException(
            status_code=404, detail=f"Policy with ID '{policy_id}' not found"
        )

    ctl_res = await db.execute(select(Control).where(Control.id == control_id))
    control = ctl_res.scalars().first()
    if control is None:
        raise HTTPException(
            status_code=404, detail=f"Control with ID '{control_id}' not found"
        )

    # Remove association (idempotent - deleting non-existent is no-op)
    try:
        await db.execute(
            delete(policy_controls).where(
                (policy_controls.c.policy_id == policy_id)
                & (policy_controls.c.control_id == control_id)
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to remove control '{control.name}' ({control_id}) "
            f"from policy '{policy.name}' ({policy_id})",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to remove control '{control.name}' from policy '{policy.name}': "
                "database error"
            ),
        )

    return AssocResponse(success=True)


@router.get(
    "/{policy_id}/controls",
    response_model=GetPolicyControlsResponse,
    summary="List policy's controls",
    response_description="List of control IDs",
)
async def list_policy_controls(
    policy_id: int, db: AsyncSession = Depends(get_async_db)
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
    pol_res = await db.execute(select(Policy.id).where(Policy.id == policy_id))
    if pol_res.first() is None:
        raise HTTPException(
            status_code=404, detail=f"Policy with ID '{policy_id}' not found"
        )

    rows = await db.execute(
        select(policy_controls.c.control_id).where(
            policy_controls.c.policy_id == policy_id
        )
    )
    control_ids = [r[0] for r in rows.fetchall()]
    return GetPolicyControlsResponse(control_ids=control_ids)
