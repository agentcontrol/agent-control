"""Tenant-scoped lookup helpers.

Every request-scoped access to a tenant-owned row (Agent, Control, Policy,
Target) goes through one of the helpers in this module so that the tenant
boundary is enforced consistently across endpoints. Rows owned by a
different tenant surface as ``404 NOT_FOUND`` rather than leaking existence
through a different status code.

This is not full tenant independence: ``Agent.name``, ``Control.name``, and
``Policy.name`` are still globally unique at the schema level. What these
helpers enforce is the *access* boundary: a caller resolved to tenant A
cannot read, mutate, or reference a row stamped with tenant B.
"""

from __future__ import annotations

from agent_control_models.errors import ErrorCode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import NotFoundError
from ..models import Agent, Control, Policy


async def get_agent_in_tenant_or_404(
    *, tenant_id: str, agent_name: str, db: AsyncSession
) -> Agent:
    """Return the agent row scoped to the given tenant, or raise 404.

    The same ``AGENT_NOT_FOUND`` code is returned whether the agent does not
    exist at all or belongs to a different tenant, to avoid leaking the
    presence of rows owned by other tenants.
    """
    stmt = select(Agent).where(
        Agent.name == agent_name, Agent.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    agent = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with name '{agent_name}' not found",
            resource="Agent",
            resource_id=agent_name,
            hint="Verify the agent name and that the agent belongs to this tenant.",
        )
    return agent


async def get_policy_in_tenant_or_404(
    *, tenant_id: str, policy_id: int, db: AsyncSession
) -> Policy:
    """Return the policy row scoped to the given tenant, or raise 404."""
    stmt = select(Policy).where(
        Policy.id == policy_id, Policy.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    policy = result.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID and that the policy belongs to this tenant.",
        )
    return policy


async def get_control_in_tenant_or_404(
    *, tenant_id: str, control_id: int, db: AsyncSession
) -> Control:
    """Return the control row scoped to the given tenant, or raise 404."""
    stmt = select(Control).where(
        Control.id == control_id, Control.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    control = result.scalars().first()
    if control is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID and that the control belongs to this tenant.",
        )
    return control


