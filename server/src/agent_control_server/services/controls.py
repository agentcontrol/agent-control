from __future__ import annotations

import datetime as dt
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
from sqlalchemy import Integer, String, delete, func, literal, or_, select, union, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from ..errors import APIValidationError, NotFoundError
from ..models import Control, ControlVersion, agent_controls, agent_policies, policy_controls
from .control_definitions import (
    parse_control_definition_or_api_error,
    parse_runtime_control_definition_or_api_error,
)
from .query_utils import escape_like_pattern

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


@dataclass(frozen=True)
class ControlListPage:
    """Paginated control rows for browse/list endpoints."""

    controls: list[Control]
    total: int
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True)
class ControlUsage:
    """Usage attribution summary for a listed control."""

    representative_agent_name: str | None
    used_by_agents_count: int


@dataclass(frozen=True)
class ControlAssociations:
    """Policy and agent associations for a control."""

    policy_ids: list[int]
    agent_names: list[str]


@dataclass(frozen=True)
class RemoveAgentControlResult:
    """Outcome for removing a direct control association from an agent."""

    removed_direct_association: bool
    control_still_active: bool


class ControlService:
    """Shared control persistence helpers used by server endpoints."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def create_control(self, *, name: str, data: dict[str, Any]) -> Control:
        """Create a new pending control row."""
        control = Control(name=name, data=data)
        self._db.add(control)
        return control

    @staticmethod
    def rename_control(control: Control, *, name: str) -> None:
        """Update a control name in-memory before commit."""
        control.name = name

    @staticmethod
    def replace_control_data(control: Control, *, data: dict[str, Any]) -> None:
        """Replace the stored JSON payload for a control."""
        control.data = data

    @staticmethod
    def set_control_enabled(control: Control, *, enabled: bool) -> None:
        """Persist a new enabled flag on an existing control payload."""
        updated_data = dict(control.data)
        updated_data["enabled"] = enabled
        control.data = updated_data

    @staticmethod
    def mark_control_deleted(control: Control, *, deleted_at: dt.datetime) -> None:
        """Mark a control as soft-deleted."""
        control.deleted_at = deleted_at

    async def get_control_or_404(
        self,
        control_id: int,
        *,
        for_update: bool = False,
    ) -> Control:
        """Load any control row, including soft-deleted controls."""
        stmt = select(Control).where(Control.id == control_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._db.execute(stmt)
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

    async def get_active_control_or_404(
        self,
        control_id: int,
        *,
        for_update: bool = False,
    ) -> Control:
        """Load an active control row or raise CONTROL_NOT_FOUND."""
        stmt = select(Control).where(Control.id == control_id, Control.deleted_at.is_(None))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._db.execute(stmt)
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
        await self._lock_control_row(control.id)

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

    async def list_controls_for_policy(self, policy_id: int) -> list[Control]:
        """Return DB control rows directly associated with a policy."""
        stmt = (
            select(Control)
            .join(policy_controls, Control.id == policy_controls.c.control_id)
            .where(policy_controls.c.policy_id == policy_id, Control.deleted_at.is_(None))
            .order_by(Control.id)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_policy_control_ids(self, policy_id: int) -> list[int]:
        """Return active control IDs directly associated with a policy."""
        result = await self._db.execute(
            select(policy_controls.c.control_id)
            .join(Control, Control.id == policy_controls.c.control_id)
            .where(policy_controls.c.policy_id == policy_id, Control.deleted_at.is_(None))
            .order_by(policy_controls.c.control_id)
        )
        return [cast(int, row[0]) for row in result.all()]

    async def list_controls_for_agent(
        self,
        agent_name: str,
        *,
        allow_invalid_step_name_regex: bool = False,
        rendered_state: AgentControlRenderedState = "rendered",
        enabled_state: AgentControlEnabledState = "enabled",
    ) -> list[APIControl]:
        """Return API control models for controls associated with an agent.

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
        db_controls = await self._list_db_controls_for_agent(agent_name)

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
        self,
        agent_name: str,
        *,
        allow_invalid_step_name_regex: bool = False,
    ) -> list[RuntimeControl]:
        """Return runtime-parsed controls for evaluation hot paths."""
        db_controls = await self._list_db_controls_for_agent(agent_name)

        runtime_controls: list[RuntimeControl] = []
        for control in db_controls:
            # Skip unrendered template controls - they have no condition to evaluate.
            if _is_unrendered_template_payload(control.data):
                continue

            context = (
                {"allow_invalid_step_name_regex": True}
                if allow_invalid_step_name_regex
                else None
            )
            control_def = parse_runtime_control_definition_or_api_error(
                control.data,
                detail=f"Control '{control.name}' has corrupted data",
                resource_id=str(control.id),
                hint=f"Update the control data using PUT /api/v1/controls/{control.id}/data.",
                context=context,
                field_prefix="data",
            )
            runtime_controls.append(
                RuntimeControl(id=control.id, name=control.name, control=control_def)
            )
        return runtime_controls

    async def list_controls_page(
        self,
        *,
        cursor: int | None,
        limit: int,
        name: str | None,
        enabled: bool | None,
        template_backed: bool | None,
        step_type: str | None,
        stage: str | None,
        execution: str | None,
        tag: str | None,
    ) -> ControlListPage:
        """Return paginated active controls for the browse endpoint."""
        query = select(Control).where(Control.deleted_at.is_(None)).order_by(Control.id.desc())
        query = self._apply_control_list_filters(
            query,
            name=name,
            enabled=enabled,
            template_backed=template_backed,
            step_type=step_type,
            stage=stage,
            execution=execution,
            tag=tag,
        )
        if cursor is not None:
            query = query.where(Control.id < cursor)

        result = await self._db.execute(query.limit(limit + 1))
        controls = list(result.scalars().all())

        total_query = select(func.count()).select_from(Control).where(Control.deleted_at.is_(None))
        total_query = self._apply_control_list_filters(
            total_query,
            name=name,
            enabled=enabled,
            template_backed=template_backed,
            step_type=step_type,
            stage=stage,
            execution=execution,
            tag=tag,
        )
        total_result = await self._db.execute(total_query)
        total = cast(int, total_result.scalar_one())

        has_more = len(controls) > limit
        if has_more:
            controls = controls[:-1]

        next_cursor: str | None = None
        if has_more and controls:
            next_cursor = str(controls[-1].id)

        return ControlListPage(
            controls=controls,
            total=total,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def list_control_usage(self, control_ids: Sequence[int]) -> dict[int, ControlUsage]:
        """Return representative agent usage and usage counts for the provided controls."""
        if not control_ids:
            return {}

        usage_names: dict[int, set[str]] = {control_id: set() for control_id in control_ids}
        policy_agents_query = (
            select(
                policy_controls.c.control_id,
                agent_policies.c.agent_name,
            )
            .select_from(policy_controls)
            .join(agent_policies, policy_controls.c.policy_id == agent_policies.c.policy_id)
            .where(policy_controls.c.control_id.in_(control_ids))
        )
        direct_agents_query = (
            select(
                agent_controls.c.control_id,
                agent_controls.c.agent_name,
            )
            .select_from(agent_controls)
            .where(agent_controls.c.control_id.in_(control_ids))
        )
        agents_result = await self._db.execute(union_all(policy_agents_query, direct_agents_query))
        for control_id, agent_name in agents_result.all():
            usage_names[cast(int, control_id)].add(cast(str, agent_name))

        return {
            control_id: ControlUsage(
                representative_agent_name=min(agent_names) if agent_names else None,
                used_by_agents_count=len(agent_names),
            )
            for control_id, agent_names in usage_names.items()
        }

    async def list_active_control_counts_by_agent(
        self,
        agent_names: Sequence[str],
    ) -> dict[str, int]:
        """Return active control counts keyed by agent name."""
        if not agent_names:
            return {}

        policy_associations = (
            select(
                agent_policies.c.agent_name.label("agent_name"),
                policy_controls.c.control_id.label("control_id"),
            )
            .select_from(
                agent_policies.join(
                    policy_controls, agent_policies.c.policy_id == policy_controls.c.policy_id
                )
            )
            .where(agent_policies.c.agent_name.in_(agent_names))
        )
        direct_associations = select(
            agent_controls.c.agent_name.label("agent_name"),
            agent_controls.c.control_id.label("control_id"),
        ).where(agent_controls.c.agent_name.in_(agent_names))
        all_associations = union_all(policy_associations, direct_associations).subquery()

        result = await self._db.execute(
            select(
                all_associations.c.agent_name,
                func.count(func.distinct(all_associations.c.control_id)).label("count"),
            )
            .join(Control, all_associations.c.control_id == Control.id)
            .where(
                Control.deleted_at.is_(None),
                or_(
                    Control.data["enabled"].astext == "true",
                    ~Control.data.has_key("enabled"),
                ),
            )
            .group_by(all_associations.c.agent_name)
        )
        return {cast(str, row[0]): cast(int, row[1]) for row in result.all()}

    async def add_control_to_policy(self, *, policy_id: int, control_id: int) -> None:
        """Create a policy-control association if it does not already exist."""
        await self._db.execute(
            pg_insert(policy_controls)
            .values(policy_id=policy_id, control_id=control_id)
            .on_conflict_do_nothing()
        )

    async def remove_control_from_policy(self, *, policy_id: int, control_id: int) -> None:
        """Remove a policy-control association if it exists."""
        await self._db.execute(
            delete(policy_controls).where(
                (policy_controls.c.policy_id == policy_id)
                & (policy_controls.c.control_id == control_id)
            )
        )

    async def add_control_to_agent(self, *, agent_name: str, control_id: int) -> None:
        """Create a direct agent-control association if it does not already exist."""
        await self._db.execute(
            pg_insert(agent_controls)
            .values(agent_name=agent_name, control_id=control_id)
            .on_conflict_do_nothing()
        )

    async def remove_control_from_agent(
        self,
        *,
        agent_name: str,
        control_id: int,
    ) -> RemoveAgentControlResult:
        """Remove a direct agent-control association and report remaining active state."""
        remove_direct_result = await self._db.execute(
            delete(agent_controls)
            .where(
                (agent_controls.c.agent_name == agent_name)
                & (agent_controls.c.control_id == control_id)
            )
            .returning(agent_controls.c.control_id)
        )
        removed_direct_association = remove_direct_result.first() is not None

        policy_inheritance_result = await self._db.execute(
            select(policy_controls.c.control_id)
            .select_from(
                agent_policies.join(
                    policy_controls,
                    agent_policies.c.policy_id == policy_controls.c.policy_id,
                )
            )
            .where(
                (agent_policies.c.agent_name == agent_name)
                & (policy_controls.c.control_id == control_id)
            )
            .limit(1)
        )
        return RemoveAgentControlResult(
            removed_direct_association=removed_direct_association,
            control_still_active=policy_inheritance_result.first() is not None,
        )

    async def list_control_associations(self, control_id: int) -> ControlAssociations:
        """Return all policy and direct agent associations for a control."""
        policy_assoc_query = select(
            policy_controls.c.policy_id.label("policy_id"),
            literal(None, type_=String).label("agent_name"),
        ).where(policy_controls.c.control_id == control_id)
        agent_assoc_query = select(
            literal(None, type_=Integer).label("policy_id"),
            agent_controls.c.agent_name.label("agent_name"),
        ).where(agent_controls.c.control_id == control_id)
        assoc_result = await self._db.execute(union_all(policy_assoc_query, agent_assoc_query))

        policy_ids: set[int] = set()
        agent_names: set[str] = set()
        for policy_id, agent_name in assoc_result.all():
            if policy_id is not None:
                policy_ids.add(cast(int, policy_id))
            if agent_name is not None:
                agent_names.add(cast(str, agent_name))

        return ControlAssociations(
            policy_ids=sorted(policy_ids),
            agent_names=sorted(agent_names),
        )

    async def remove_all_control_associations(self, control_id: int) -> ControlAssociations:
        """Remove all policy and direct agent associations for a control."""
        associations = await self.list_control_associations(control_id)
        if associations.policy_ids:
            await self._db.execute(
                delete(policy_controls).where(policy_controls.c.control_id == control_id)
            )
        if associations.agent_names:
            await self._db.execute(
                delete(agent_controls).where(agent_controls.c.control_id == control_id)
            )
        return associations

    async def _next_version_num(self, control_id: int) -> int:
        """Compute the next monotonically increasing version number for a control."""
        result = await self._db.execute(
            select(func.coalesce(func.max(ControlVersion.version_num), 0) + 1).where(
                ControlVersion.control_id == control_id
            )
        )
        return cast(int, result.scalar_one())

    async def _lock_control_row(self, control_id: int) -> None:
        """Serialize version creation on a control by taking a row-level lock."""
        await self._db.execute(
            select(Control.id).where(Control.id == control_id).with_for_update()
        )

    async def _list_db_controls_for_agent(self, agent_name: str) -> Sequence[Control]:
        """Return DB control rows associated with an agent."""
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

        result = await self._db.execute(stmt)
        return result.scalars().unique().all()

    def _apply_control_list_filters(
        self,
        stmt: Select[Any],
        *,
        name: str | None,
        enabled: bool | None,
        template_backed: bool | None,
        step_type: str | None,
        stage: str | None,
        execution: str | None,
        tag: str | None,
    ) -> Select[Any]:
        """Apply browse/list filters to a control query."""
        if name is not None:
            stmt = stmt.where(
                Control.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\")
            )

        if enabled is not None:
            if enabled:
                stmt = stmt.where(
                    or_(
                        Control.data["enabled"].astext == "true",
                        ~Control.data.has_key("enabled"),
                    )
                )
            else:
                stmt = stmt.where(Control.data["enabled"].astext == "false")

        if template_backed is not None:
            if template_backed:
                stmt = stmt.where(Control.data.has_key("template"))
            else:
                stmt = stmt.where(~Control.data.has_key("template"))

        has_rendered_filter = any(f is not None for f in (step_type, stage, execution, tag))
        if has_rendered_filter:
            stmt = stmt.where(Control.data.has_key("condition"))

        if step_type is not None:
            stmt = stmt.where(
                or_(
                    Control.data["scope"]["step_types"].contains([step_type]),
                    ~Control.data.has_key("scope"),
                    ~Control.data["scope"].has_key("step_types"),
                )
            )
        if stage is not None:
            stmt = stmt.where(
                or_(
                    Control.data["scope"]["stages"].contains([stage]),
                    ~Control.data.has_key("scope"),
                    ~Control.data["scope"].has_key("stages"),
                )
            )
        if execution is not None:
            stmt = stmt.where(Control.data["execution"].astext == execution)
        if tag is not None:
            stmt = stmt.where(Control.data["tags"].contains([tag]))

        return stmt

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
