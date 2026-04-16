from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from agent_control_models import (
    ControlDefinition,
    ControlDefinitionRuntime,
    UnrenderedTemplateControl,
)
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.policy import Control as APIControl
from pydantic import ValidationError
from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import APIValidationError, NotFoundError
from ..logging_utils import get_logger
from ..models import Control, ControlVersion, agent_controls, agent_policies, policy_controls
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


@dataclass(frozen=True)
class ControlVersionPage:
    """Paginated control-version results."""

    versions: list[ControlVersion]
    total: int
    has_more: bool
    next_cursor: str | None


class ControlService:
    """Shared control persistence helpers used by server endpoints."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_control_or_404(self, control_id: int) -> Control:
        """Load any control row, including soft-deleted controls."""
        result = await self._db.execute(select(Control).where(Control.id == control_id))
        control = cast(Control | None, result.scalars().first())
        if control is None:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_NOT_FOUND,
                detail=f"Control with ID '{control_id}' not found",
                resource="Control",
                resource_id=str(control_id),
                hint="Verify the control ID is correct and the control has been created.",
            )
        return control

    async def get_active_control_or_404(self, control_id: int) -> Control:
        """Load an active control row or raise CONTROL_NOT_FOUND."""
        result = await self._db.execute(
            select(Control).where(Control.id == control_id, Control.deleted_at.is_(None))
        )
        control = cast(Control | None, result.scalars().first())
        if control is None:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_NOT_FOUND,
                detail=f"Control with ID '{control_id}' not found",
                resource="Control",
                resource_id=str(control_id),
                hint="Verify the control ID is correct and the control has been created.",
            )
        return control

    async def active_control_name_exists(
        self,
        name: str,
        *,
        exclude_control_id: int | None = None,
    ) -> bool:
        """Return whether an active control already uses the provided name."""
        stmt = select(Control.id).where(Control.name == name, Control.deleted_at.is_(None))
        if exclude_control_id is not None:
            stmt = stmt.where(Control.id != exclude_control_id)
        result = await self._db.execute(stmt)
        return result.first() is not None

    async def create_version(
        self,
        control: Control,
        *,
        event_type: str,
        note: str,
    ) -> ControlVersion:
        """Append a new immutable version row for the current control state."""
        await self._db.flush()

        next_version_num = await self._next_version_num(control.id)
        version = ControlVersion(
            control_id=control.id,
            version_num=next_version_num,
            event_type=event_type,
            snapshot=self._build_snapshot(control),
            note=note,
        )
        self._db.add(version)
        await self._db.flush()
        return version

    async def list_versions(
        self,
        control_id: int,
        *,
        cursor: int | None,
        limit: int,
    ) -> ControlVersionPage:
        """Return control versions newest-first with cursor pagination."""
        await self.get_control_or_404(control_id)

        total_result = await self._db.execute(
            select(func.count())
            .select_from(ControlVersion)
            .where(ControlVersion.control_id == control_id)
        )
        total = cast(int, total_result.scalar_one())

        stmt = (
            select(ControlVersion)
            .where(ControlVersion.control_id == control_id)
            .order_by(ControlVersion.version_num.desc())
        )
        if cursor is not None:
            stmt = stmt.where(ControlVersion.version_num < cursor)

        result = await self._db.execute(stmt.limit(limit + 1))
        versions = list(result.scalars().all())

        has_more = len(versions) > limit
        if has_more:
            versions = versions[:-1]

        next_cursor: str | None = None
        if has_more and versions:
            next_cursor = str(versions[-1].version_num)

        return ControlVersionPage(
            versions=versions,
            total=total,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def get_version_or_404(self, control_id: int, version_num: int) -> ControlVersion:
        """Load a specific version row for a control."""
        await self.get_control_or_404(control_id)

        result = await self._db.execute(
            select(ControlVersion).where(
                ControlVersion.control_id == control_id,
                ControlVersion.version_num == version_num,
            )
        )
        version = cast(ControlVersion | None, result.scalars().first())
        if version is None:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_VERSION_NOT_FOUND,
                detail=(
                    f"Version '{version_num}' for control with ID '{control_id}' not found"
                ),
                resource="ControlVersion",
                resource_id=f"{control_id}:{version_num}",
                hint="Verify the control ID and version number are correct.",
            )
        return version

    async def _next_version_num(self, control_id: int) -> int:
        """Compute the next monotonically increasing version number for a control."""
        result = await self._db.execute(
            select(func.coalesce(func.max(ControlVersion.version_num), 0) + 1).where(
                ControlVersion.control_id == control_id
            )
        )
        return cast(int, result.scalar_one())

    @staticmethod
    def _build_snapshot(control: Control) -> dict[str, Any]:
        """Serialize the persisted control state stored in version history."""
        deleted_at = control.deleted_at.isoformat() if control.deleted_at is not None else None
        cloned_control_id = cast(int | None, getattr(control, "cloned_control_id", None))
        return {
            "name": control.name,
            "data": control.data,
            "deleted_at": deleted_at,
            "cloned_control_id": cloned_control_id,
        }


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
        .where(Control.deleted_at.is_(None))
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
        .where(policy_controls.c.policy_id == policy_id, Control.deleted_at.is_(None))
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
