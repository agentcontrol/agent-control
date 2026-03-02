from __future__ import annotations

import logging
from collections.abc import Sequence

from agent_control_models import ControlDefinition
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.policy import Control as APIControl
from pydantic import ValidationError
from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import APIValidationError
from ..models import Control, agent_controls, agent_policies, policy_controls

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

    stmt = select(Control).join(
        control_ids_subquery, Control.id == control_ids_subquery.c.control_id
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
