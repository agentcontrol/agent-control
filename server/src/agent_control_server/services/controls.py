from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from agent_control_models import ControlDefinition
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.policy import Control as APIControl
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import APIValidationError
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


async def list_controls_for_agent(
    agent_id: UUID,
    db: AsyncSession,
    *,
    allow_invalid_step_name_regex: bool = False,
) -> list[APIControl]:
    """Return API Control models for all configured controls associated with the agent's policy.

    Traversal: Agent -> Policy -> Controls (direct relationship).
    Uses explicit joins over association table to avoid async relationship loading.

    Note: Invalid ControlDefinition data triggers an APIValidationError.
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

    # Map DB Control to API Control, raising on invalid definitions
    api_controls: list[APIControl] = []
    for c in db_controls:
        try:
            context = (
                {"allow_invalid_step_name_regex": True}
                if allow_invalid_step_name_regex
                else None
            )
            control_def = ControlDefinition.model_validate(c.data, context=context)
            api_controls.append(APIControl(id=c.id, name=c.name, control=control_def))
        except ValidationError as e:
            error_items = []
            for err in e.errors():
                loc: Sequence[str | int] = err.get("loc", [])
                field_suffix = ".".join(str(part) for part in loc) if loc else ""
                error_items.append(
                    ValidationErrorItem(
                        resource="Control",
                        field=f"data.{field_suffix}" if field_suffix else "data",
                        code=err.get("type", "validation_error"),
                        message=err.get("msg", "Validation failed"),
                    )
                )

            raise APIValidationError(
                error_code=ErrorCode.CORRUPTED_DATA,
                detail=f"Control '{c.name}' has corrupted data",
                resource="Control",
                resource_id=str(c.id),
                hint=(
                    "Update the control data using "
                    f"PUT /api/v1/controls/{c.id}/data."
                ),
                errors=error_items,
            ) from e
    return api_controls
