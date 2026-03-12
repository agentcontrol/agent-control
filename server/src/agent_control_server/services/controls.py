from __future__ import annotations

from collections.abc import Sequence

from agent_control_models.policy import Control as APIControl
from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Control, agent_controls, agent_policies, policy_controls
from .control_definitions import parse_control_definition_or_api_error


async def list_controls_for_policy(policy_id: int, db: AsyncSession) -> list[Control]:
    """Return DB Control objects for all controls directly associated with a policy."""
    stmt = (
        select(Control)
        .join(policy_controls, Control.id == policy_controls.c.control_id)
        .where(policy_controls.c.policy_id == policy_id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def list_controls_for_agent(
    agent_name: str,
    db: AsyncSession,
    *,
    allow_invalid_step_name_regex: bool = False,
) -> list[APIControl]:
    """Return API Control models for controls associated with the agent.

    Active controls are the de-duplicated union of:
    - controls inherited from all assigned policies
    - controls directly associated with the agent

    Note: Invalid ControlDefinition data triggers an APIValidationError.
    """
    policy_control_ids = (
        select(policy_controls.c.control_id.label("control_id"))
        .select_from(
            policy_controls.join(
                agent_policies, policy_controls.c.policy_id == agent_policies.c.policy_id
            )
        )
        .where(agent_policies.c.agent_name == agent_name)
    )
    direct_control_ids = select(agent_controls.c.control_id.label("control_id")).where(
        agent_controls.c.agent_name == agent_name
    )
    control_ids_subquery = union(policy_control_ids, direct_control_ids).subquery()

    stmt = (
        select(Control)
        .join(control_ids_subquery, Control.id == control_ids_subquery.c.control_id)
        .order_by(Control.id.desc())
    )

    result = await db.execute(stmt)
    db_controls: Sequence[Control] = result.scalars().unique().all()

    # Map DB Control to API Control, raising on invalid definitions
    api_controls: list[APIControl] = []
    for c in db_controls:
        context = (
            {"allow_invalid_step_name_regex": True}
            if allow_invalid_step_name_regex
            else None
        )
        control_def = parse_control_definition_or_api_error(
            c.data,
            detail=f"Control '{c.name}' has corrupted data",
            resource_id=str(c.id),
            hint=f"Update the control data using PUT /api/v1/controls/{c.id}/data.",
            context=context,
            field_prefix="data",
        )
        api_controls.append(APIControl(id=c.id, name=c.name, control=control_def))
    return api_controls
