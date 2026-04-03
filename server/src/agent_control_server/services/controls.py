from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from agent_control_models import (
    ControlDefinition,
    ControlDefinitionRuntime,
    UnrenderedTemplateControl,
)
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.policy import Control as APIControl
from pydantic import ValidationError
from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import APIValidationError
from ..logging_utils import get_logger
from ..models import Control, agent_controls, agent_policies, policy_controls
from .control_definitions import (
    parse_control_definition_or_api_error,
    parse_runtime_control_definition_or_api_error,
)

_logger = get_logger(__name__)

type AgentControlRenderedState = Literal["rendered", "unrendered", "all"]
type AgentControlEnabledState = Literal["enabled", "disabled", "all"]


@dataclass(frozen=True)
class RuntimeControl:
    """Internal runtime control payload for evaluation hot paths."""

    id: int
    name: str
    control: ControlDefinitionRuntime


async def _list_db_controls_for_agent(
    agent_name: str,
    db: AsyncSession,
) -> Sequence[Control]:
    """Return DB Control rows for the controls associated with an agent."""
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
    return result.scalars().unique().all()


def _is_unrendered_template_payload(data: object) -> bool:
    """Return whether stored JSON looks like an unrendered template control."""
    return (
        isinstance(data, dict)
        and data.get("template") is not None
        and data.get("condition") is None
    )


def _parse_unrendered_template_or_api_error(control: Control) -> UnrenderedTemplateControl:
    """Parse an unrendered template control or raise the standard corrupted-data error."""
    try:
        return UnrenderedTemplateControl.model_validate(control.data)
    except ValidationError as exc:
        raise APIValidationError(
            error_code=ErrorCode.CORRUPTED_DATA,
            detail=f"Control '{control.name}' has corrupted unrendered template data",
            resource="Control",
            resource_id=str(control.id),
            hint=f"Update the control data using PUT /api/v1/controls/{control.id}/data.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field="data",
                    code="corrupted_data",
                    message="Stored unrendered template data is invalid.",
                )
            ],
        ) from exc


def _parse_associated_control_or_api_error(
    control: Control,
    *,
    allow_invalid_step_name_regex: bool = False,
) -> APIControl:
    """Parse an associated control row into the API model or raise a validation error."""
    if _is_unrendered_template_payload(control.data):
        unrendered = _parse_unrendered_template_or_api_error(control)
        return APIControl(id=control.id, name=control.name, control=unrendered)

    context = (
        {"allow_invalid_step_name_regex": True}
        if allow_invalid_step_name_regex
        else None
    )
    control_def = parse_control_definition_or_api_error(
        control.data,
        detail=f"Control '{control.name}' has corrupted data",
        resource_id=str(control.id),
        hint=f"Update the control data using PUT /api/v1/controls/{control.id}/data.",
        context=context,
        field_prefix="data",
    )
    return APIControl(id=control.id, name=control.name, control=control_def)


def _matches_rendered_state(
    control: APIControl,
    rendered_state: AgentControlRenderedState,
) -> bool:
    """Return whether a parsed control matches the requested rendered-state filter."""
    is_rendered = isinstance(control.control, ControlDefinition)
    if rendered_state == "all":
        return True
    if rendered_state == "rendered":
        return is_rendered
    return not is_rendered


def _matches_enabled_state(
    control: APIControl,
    enabled_state: AgentControlEnabledState,
) -> bool:
    """Return whether a parsed control matches the requested enabled-state filter."""
    if enabled_state == "all":
        return True
    is_enabled = control.control.enabled
    if enabled_state == "enabled":
        return is_enabled
    return not is_enabled


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
    rendered_state: AgentControlRenderedState = "rendered",
    enabled_state: AgentControlEnabledState = "enabled",
) -> list[APIControl]:
    """Return API Control models for controls associated with the agent.

    Associated controls are the de-duplicated union of:
    - controls inherited from all assigned policies
    - controls directly associated with the agent

    By default, only active controls are returned. "Active" means rendered
    and enabled. Callers can broaden the returned set via rendered_state and
    enabled_state filters. Filters intersect, so unrendered drafts require
    rendered_state="unrendered" together with enabled_state="all" or
    enabled_state="disabled".

    Note: Any corrupted associated control row triggers APIValidationError,
    even if filters would otherwise exclude it.
    """
    db_controls = await _list_db_controls_for_agent(agent_name, db)

    parsed_controls = [
        _parse_associated_control_or_api_error(
            control,
            allow_invalid_step_name_regex=allow_invalid_step_name_regex,
        )
        for control in db_controls
    ]
    return [
        control
        for control in parsed_controls
        if _matches_rendered_state(control, rendered_state)
        and _matches_enabled_state(control, enabled_state)
    ]


async def list_runtime_controls_for_agent(
    agent_name: str,
    db: AsyncSession,
    *,
    allow_invalid_step_name_regex: bool = False,
) -> list[RuntimeControl]:
    """Return runtime-parsed controls for evaluation hot paths."""
    db_controls = await _list_db_controls_for_agent(agent_name, db)

    runtime_controls: list[RuntimeControl] = []
    for c in db_controls:
        # Skip unrendered template controls — they have no condition to evaluate.
        if _is_unrendered_template_payload(c.data):
            continue

        context = (
            {"allow_invalid_step_name_regex": True}
            if allow_invalid_step_name_regex
            else None
        )
        control_def = parse_runtime_control_definition_or_api_error(
            c.data,
            detail=f"Control '{c.name}' has corrupted data",
            resource_id=str(c.id),
            hint=f"Update the control data using PUT /api/v1/controls/{c.id}/data.",
            context=context,
            field_prefix="data",
        )
        runtime_controls.append(RuntimeControl(id=c.id, name=c.name, control=control_def))
    return runtime_controls
