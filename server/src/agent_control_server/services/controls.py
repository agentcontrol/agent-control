from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from agent_control_models import ControlDefinition
from agent_control_models.policy import Control as APIControl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, Control, Policy, policy_controls

_logger = logging.getLogger(__name__)


async def list_controls_for_policy(policy_id: int, db: AsyncSession) -> list[Control]:
    """Return DB Control objects for all controls directly associated with a policy."""
    stmt = (
        select(Control)
        .join(policy_controls, Control.id == policy_controls.c.control_id)
        .where(policy_controls.c.policy_id == policy_id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def list_controls_for_agent(agent_id: UUID, db: AsyncSession) -> list[APIControl]:
    """Return API Control models for all configured controls associated with the agent's policy.

    Traversal: Agent -> Policy -> Controls (direct relationship).
    Uses explicit joins over association table to avoid async relationship loading.

    Note: Unconfigured controls (empty data or invalid ControlDefinition) are filtered out.
    """
    stmt = (
        select(Control)
        .join(policy_controls, Control.id == policy_controls.c.control_id)
        .join(Policy, policy_controls.c.policy_id == Policy.id)
        .join(Agent, Policy.id == Agent.policy_id)
        .where(Agent.agent_uuid == agent_id)
    )

    result = await db.execute(stmt)
    db_controls: Sequence[Control] = result.scalars().unique().all()

    # Map DB Control to API Control, filtering out unconfigured controls
    api_controls: list[APIControl] = []
    for c in db_controls:
        try:
            control_def = ControlDefinition.model_validate(c.data)
            api_controls.append(APIControl(id=c.id, name=c.name, control=control_def))
        except Exception:
            # Skip unconfigured or invalid controls
            _logger.warning(
                "Skipping unconfigured control '%s' (id=%s) for agent %s",
                c.name,
                c.id,
                agent_id,
            )
    return api_controls
