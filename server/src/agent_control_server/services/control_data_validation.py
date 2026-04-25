"""Control data parsing, serialization, and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_control_engine import list_evaluators
from agent_control_models import (
    ControlDefinition,
    TemplateControlInput,
    UnrenderedTemplateControl,
)
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import SlugName
from jsonschema_rs import ValidationError as JSONSchemaValidationError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import APIValidationError, ConflictError, NotFoundError
from ..logging_utils import get_logger
from ..models import Agent, AgentData
from .condition_traversal import iter_condition_leaves_with_paths
from .control_definitions import (
    build_control_validation_errors,
    parse_control_definition_or_api_error,
)
from .control_templates import (
    can_render_template,
    remap_template_api_error,
    render_template_control_input,
    validate_partial_template_values,
    validate_template_structure,
)
from .evaluator_utils import (
    parse_evaluator_ref_full,
    validate_config_against_schema,
)
from .validation_paths import format_field_path

_INVALID_PARAMETERS_MESSAGE = "Invalid config parameters for evaluator."
_SCHEMA_VALIDATION_FAILED_MESSAGE = "Config does not satisfy the evaluator schema."

_SLUG_NAME_ADAPTER = TypeAdapter(SlugName)
_logger = get_logger(__name__)


@dataclass(frozen=True)
class RestorableControlSnapshot:
    """Validated state extracted from a control-version snapshot."""

    name: str
    data: dict[str, Any]


def serialize_control_data(
    control_data: ControlDefinition | UnrenderedTemplateControl,
) -> dict[str, Any]:
    """Serialize control data for JSONB storage."""
    data_json = control_data.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
        exclude_unset=True,
    )
    if "scope" in data_json and isinstance(data_json["scope"], dict):
        data_json["scope"] = {k: v for k, v in data_json["scope"].items() if v is not None}
    # Always persist enabled explicitly so enabled_from_stored_payload reads
    # the correct value (especially for unrendered templates where enabled=False).
    if "enabled" not in data_json:
        data_json["enabled"] = control_data.enabled
    return data_json


def is_template_backed_payload(data: object) -> bool:
    """Return whether stored control JSON contains template metadata."""
    return isinstance(data, dict) and data.get("template") is not None


def is_unrendered_template(data: object) -> bool:
    """Return whether stored control JSON is an unrendered template."""
    return (
        isinstance(data, dict)
        and data.get("template") is not None
        and data.get("condition") is None
    )


def parse_stored_control_data(
    data: dict[str, object],
    *,
    control_name: str,
    control_id: int,
) -> ControlDefinition | UnrenderedTemplateControl:
    """Parse stored JSONB into the appropriate model type."""
    if is_unrendered_template(data):
        try:
            return UnrenderedTemplateControl.model_validate(data)
        except ValidationError as exc:
            raise APIValidationError(
                error_code=ErrorCode.CORRUPTED_DATA,
                detail=f"Control '{control_name}' has corrupted unrendered template data",
                resource="Control",
                resource_id=str(control_id),
                hint=f"Update the control data using PUT /api/v1/controls/{control_id}/data.",
                errors=[
                    ValidationErrorItem(
                        resource="Control",
                        field="data",
                        code="corrupted_data",
                        message="Stored unrendered template data is invalid.",
                    )
                ],
            ) from exc

    return parse_control_definition_or_api_error(
        data,
        detail=f"Control '{control_name}' has invalid data",
        hint=f"Update the control data using PUT /api/v1/controls/{control_id}/data.",
        field_prefix=None,
    )


def enabled_from_stored_payload(data: object) -> bool:
    """Return the persisted enabled flag, defaulting to True when absent."""
    if not isinstance(data, dict):
        return True
    raw_enabled = data.get("enabled", True)
    return raw_enabled if type(raw_enabled) is bool else True


async def render_and_validate_template_input(
    template_input: TemplateControlInput,
    *,
    db: AsyncSession,
    enabled: bool = True,
) -> ControlDefinition:
    """Render a template-backed input and validate evaluator config."""
    rendered = render_template_control_input(template_input, enabled=enabled)
    try:
        await validate_control_definition(rendered.control, db)
    except APIValidationError as exc:
        raise remap_template_api_error(
            exc,
            reverse_path_map=rendered.reverse_path_map,
            template=template_input.template,
        ) from exc
    return rendered.control


async def materialize_control_input(
    control_input: ControlDefinition | TemplateControlInput,
    *,
    db: AsyncSession,
    current_payload: object | None = None,
    control_id: int | None = None,
) -> ControlDefinition | UnrenderedTemplateControl:
    """Resolve raw or template-backed input into a validated control or unrendered template."""
    if isinstance(control_input, TemplateControlInput):
        if can_render_template(control_input):
            enabled = (
                True if current_payload is None else enabled_from_stored_payload(current_payload)
            )
            return await render_and_validate_template_input(
                control_input,
                db=db,
                enabled=enabled,
            )

        # Incomplete values are only allowed for new controls or already-unrendered
        # templates. Updating a rendered control with incomplete values is rejected
        # to prevent silently stripping rendered fields.
        current_is_rendered = (
            current_payload is not None
            and isinstance(current_payload, dict)
            and current_payload.get("condition") is not None
        )
        if current_is_rendered:
            # Force a full render attempt so the caller gets a clear error
            # about which required parameters are missing.
            enabled = enabled_from_stored_payload(current_payload)
            return await render_and_validate_template_input(
                control_input,
                db=db,
                enabled=enabled,
            )

        validate_template_structure(control_input.template)
        validate_partial_template_values(
            control_input.template,
            control_input.template_values,
        )
        return UnrenderedTemplateControl(
            template=control_input.template,
            template_values=dict(control_input.template_values),
            enabled=False,
        )

    if current_payload is not None and is_template_backed_payload(current_payload):
        if control_id is None:
            raise RuntimeError("control_id is required for template-backed raw updates")
        raise template_backed_raw_update_conflict(control_id)

    await validate_control_definition(control_input, db)
    return control_input


async def validate_control_definition(control_def: ControlDefinition, db: AsyncSession) -> None:
    """Validate evaluator config for definitions referencing known global evaluators.

    Agent-scoped evaluators must exist on the referenced agent. Builtin and external
    names that are not loaded in this process are accepted without config checks.
    """
    available_evaluators = list_evaluators()
    agent_data_by_name: dict[str, AgentData] = {}
    for field_prefix, leaf in iter_condition_leaves_with_paths(
        control_def.condition,
        path="data.condition",
    ):
        leaf_parts = leaf.leaf_parts()
        if leaf_parts is None:
            continue
        _, evaluator_spec = leaf_parts

        evaluator_ref = evaluator_spec.name
        parsed = parse_evaluator_ref_full(evaluator_ref)

        if parsed.type == "agent":
            agent_namespace = parsed.namespace
            if agent_namespace is None:
                continue

            agent_data = agent_data_by_name.get(agent_namespace)
            if agent_data is None:
                agent_result = await db.execute(select(Agent).where(Agent.name == agent_namespace))
                agent = agent_result.scalars().first()
                if agent is None:
                    raise NotFoundError(
                        error_code=ErrorCode.AGENT_NOT_FOUND,
                        detail=f"Agent '{agent_namespace}' not found",
                        resource="Agent",
                        resource_id=agent_namespace,
                        hint=(
                            "Ensure the agent exists before creating controls "
                            "that reference its evaluators."
                        ),
                    )

                try:
                    agent_data = AgentData.model_validate(agent.data)
                except ValidationError as exc:
                    raise APIValidationError(
                        error_code=ErrorCode.CORRUPTED_DATA,
                        detail=f"Agent '{parsed.namespace}' has invalid data",
                        resource="Agent",
                        errors=[
                            ValidationErrorItem(
                                resource="Agent",
                                field=format_field_path(err.get("loc", ())),
                                code=err.get("type", "validation_error"),
                                message=err.get("msg", "Validation failed"),
                            )
                            for err in exc.errors()
                        ],
                    ) from exc
                agent_data_by_name[agent_namespace] = agent_data

            evaluator = next(
                (e for e in (agent_data.evaluators or []) if e.name == parsed.local_name),
                None,
            )
            if evaluator is None:
                available = [e.name for e in (agent_data.evaluators or [])]
                raise APIValidationError(
                    error_code=ErrorCode.EVALUATOR_NOT_FOUND,
                    detail=(
                        f"Evaluator '{parsed.local_name}' is not registered "
                        f"with agent '{agent_namespace}'"
                    ),
                    resource="Evaluator",
                    hint=(
                        f"Register it via initAgent first. "
                        f"Available evaluators: {available or 'none'}."
                    ),
                    errors=[
                        ValidationErrorItem(
                            resource="Control",
                            field=f"{field_prefix}.evaluator.name",
                            code="evaluator_not_found",
                            message=(
                                f"Evaluator '{parsed.local_name}' not found "
                                f"on agent '{agent_namespace}'"
                            ),
                            value=evaluator_ref,
                        )
                    ],
                )

            if evaluator.config_schema:
                try:
                    validate_config_against_schema(
                        evaluator_spec.config,
                        evaluator.config_schema,
                    )
                except JSONSchemaValidationError as exc:
                    raise APIValidationError(
                        error_code=ErrorCode.INVALID_CONFIG,
                        detail=f"Config validation failed for evaluator '{evaluator_ref}'",
                        resource="Control",
                        hint=("Check the evaluator's config schema for required fields and types."),
                        errors=[
                            ValidationErrorItem(
                                resource="Control",
                                field=f"{field_prefix}.evaluator.config",
                                code="schema_validation_error",
                                message=_SCHEMA_VALIDATION_FAILED_MESSAGE,
                            )
                        ],
                    ) from exc
            continue

        evaluator_cls = available_evaluators.get(parsed.name)
        if evaluator_cls is None:
            # Global (builtin / external) evaluators may be absent from this runtime
            # (optional packages, forward compatibility). Store the definition without
            # config validation; evaluation will fail later if the evaluator is missing.
            continue

        try:
            evaluator_cls.config_model(**evaluator_spec.config)
        except ValidationError as exc:
            raise APIValidationError(
                error_code=ErrorCode.INVALID_CONFIG,
                detail=f"Config validation failed for evaluator '{parsed.name}'",
                resource="Control",
                hint="Check the evaluator's config schema for required fields and types.",
                errors=[
                    ValidationErrorItem(
                        resource="Control",
                        field=(
                            f"{field_prefix}.evaluator.config."
                            f"{format_field_path(err.get('loc', ())) or ''}"
                        ).rstrip("."),
                        code=err.get("type", "validation_error"),
                        message=err.get("msg", "Validation failed"),
                    )
                    for err in exc.errors()
                ],
            ) from exc
        except TypeError as exc:
            _logger.warning(
                "Config validation raised TypeError for evaluator '%s'",
                parsed.name,
                exc_info=True,
            )
            raise APIValidationError(
                error_code=ErrorCode.INVALID_CONFIG,
                detail=f"Invalid config parameters for evaluator '{parsed.name}'",
                resource="Control",
                hint="Check the evaluator's config schema for valid parameter names.",
                errors=[
                    ValidationErrorItem(
                        resource="Control",
                        field=f"{field_prefix}.evaluator.config",
                        code="invalid_parameters",
                        message=_INVALID_PARAMETERS_MESSAGE,
                    )
                ],
            ) from exc


def template_backed_raw_update_conflict(control_id: int) -> ConflictError:
    """Return the v1 conflict raised when raw data updates target template-backed controls."""
    return ConflictError(
        error_code=ErrorCode.CONTROL_TEMPLATE_CONFLICT,
        detail="Template-backed controls cannot be updated with raw control data in v1",
        resource="Control",
        resource_id=str(control_id),
        hint=(
            "Submit template input to update this control, or delete and recreate "
            "it as a raw control."
        ),
        errors=[
            ValidationErrorItem(
                resource="Control",
                field="data",
                code="template_backed_control_conflict",
                message="Template-backed controls must be updated with template input.",
            )
        ],
    )


async def parse_restorable_snapshot(
    snapshot: dict[str, Any],
    *,
    db: AsyncSession,
    control_id: int,
    version_num: int,
) -> RestorableControlSnapshot:
    """Validate a version snapshot against current restore rules."""
    if snapshot.get("deleted_at") is not None:
        raise APIValidationError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail=(
                f"Cannot restore version '{version_num}' for control with ID "
                f"'{control_id}' because it represents a deleted control state"
            ),
            resource="ControlVersion",
            resource_id=f"{control_id}:{version_num}",
            hint="Choose a non-deleted version to restore.",
            errors=[
                ValidationErrorItem(
                    resource="ControlVersion",
                    field="snapshot.deleted_at",
                    code="deleted_snapshot_not_restorable",
                    message="Deleted control snapshots cannot be restored in v1.",
                )
            ],
        )

    snapshot_name = _parse_snapshot_name(
        snapshot.get("name"),
        control_id=control_id,
        version_num=version_num,
    )
    snapshot_data = _parse_snapshot_data(
        snapshot.get("data"),
        control_id=control_id,
        version_num=version_num,
    )
    parsed_data = await validate_restored_control_data(
        snapshot_data,
        db=db,
        control_name=snapshot_name,
        control_id=control_id,
    )
    return RestorableControlSnapshot(
        name=snapshot_name,
        data=serialize_control_data(parsed_data),
    )


async def validate_restored_control_data(
    data: dict[str, Any],
    *,
    db: AsyncSession,
    control_name: str,
    control_id: int,
) -> ControlDefinition | UnrenderedTemplateControl:
    """Validate persisted snapshot data using current control validation rules."""
    if is_unrendered_template(data):
        try:
            unrendered = UnrenderedTemplateControl.model_validate(data)
        except ValidationError as exc:
            raise APIValidationError(
                error_code=ErrorCode.CORRUPTED_DATA,
                detail=f"Control '{control_name}' has corrupted unrendered template data",
                resource="Control",
                resource_id=str(control_id),
                hint="Restore failed because the selected version is no longer parseable.",
                errors=build_control_validation_errors(exc, field_prefix="data"),
            ) from exc

        validate_template_structure(unrendered.template)
        validate_partial_template_values(
            unrendered.template,
            unrendered.template_values,
        )
        return unrendered

    control_def = parse_control_definition_or_api_error(
        data,
        detail=f"Control '{control_name}' has invalid data",
        hint="Restore failed because the selected version is no longer parseable.",
        resource_id=str(control_id),
        field_prefix="data",
    )
    await validate_control_definition(control_def, db)
    return control_def


def _parse_snapshot_name(
    value: object,
    *,
    control_id: int,
    version_num: int,
) -> str:
    """Parse the snapshot name under current name validation rules."""
    try:
        return _SLUG_NAME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise APIValidationError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail=(
                f"Version '{version_num}' for control with ID '{control_id}' "
                "contains a name that is no longer valid"
            ),
            resource="ControlVersion",
            resource_id=f"{control_id}:{version_num}",
            hint="Choose another version or update the current control manually.",
            errors=build_control_validation_errors(exc, field_prefix="name"),
        ) from exc


def _parse_snapshot_data(
    value: object,
    *,
    control_id: int,
    version_num: int,
) -> dict[str, Any]:
    """Return snapshot data as a JSON object or raise a structured error."""
    if isinstance(value, dict):
        return dict(value)

    raise APIValidationError(
        error_code=ErrorCode.CORRUPTED_DATA,
        detail=(
            f"Version '{version_num}' for control with ID '{control_id}' "
            "does not contain a valid control data object"
        ),
        resource="ControlVersion",
        resource_id=f"{control_id}:{version_num}",
        hint="Choose another version or update the current control manually.",
        errors=[
            ValidationErrorItem(
                resource="ControlVersion",
                field="snapshot.data",
                code="invalid_snapshot_data",
                message="Snapshot data must be a JSON object.",
            )
        ],
    )
