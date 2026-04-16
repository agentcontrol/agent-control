import datetime as dt
from typing import cast

from agent_control_engine import list_evaluators
from agent_control_models import ControlDefinition, TemplateControlInput, UnrenderedTemplateControl
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
    AgentRef,
    AssocResponse,
    CloneControlRequest,
    CloneControlResponse,
    ControlSummary,
    ControlVersionSummary,
    CreateControlRequest,
    CreateControlResponse,
    DeleteControlResponse,
    GetControlDataResponse,
    GetControlResponse,
    GetControlSchemaResponse,
    GetControlVersionResponse,
    ListControlsResponse,
    ListControlVersionsResponse,
    ListPublishedControlsResponse,
    PaginationInfo,
    PatchControlRequest,
    PatchControlResponse,
    PublishedControlSummary,
    RenderControlTemplateRequest,
    RenderControlTemplateResponse,
    SetControlDataRequest,
    SetControlDataResponse,
    ValidateControlDataRequest,
    ValidateControlDataResponse,
)
from fastapi import APIRouter, Depends, Query
from jsonschema_rs import ValidationError as JSONSchemaValidationError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..db import get_async_db
from ..errors import (
    APIValidationError,
    ConflictError,
    DatabaseError,
    NotFoundError,
)
from ..logging_utils import get_logger
from ..models import Agent, AgentData
from ..services.condition_traversal import iter_condition_leaves_with_paths
from ..services.control_definitions import parse_control_definition_or_api_error
from ..services.control_templates import (
    can_render_template,
    remap_template_api_error,
    render_template_control_input,
    validate_partial_template_values,
    validate_template_structure,
)
from ..services.controls import ControlService
from ..services.evaluator_utils import (
    parse_evaluator_ref_full,
    validate_config_against_schema,
)
from ..services.validation_paths import format_field_path

# Pagination constants
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100
_INVALID_PARAMETERS_MESSAGE = "Invalid config parameters for evaluator."
_CORRUPTED_CONTROL_DATA_MESSAGE = "Stored control data is corrupted and cannot be parsed."
_SCHEMA_VALIDATION_FAILED_MESSAGE = "Config does not satisfy the evaluator schema."

router = APIRouter(prefix="/controls", tags=["controls"])
template_router = APIRouter(prefix="/control-templates", tags=["controls"])
store_router = APIRouter(prefix="/control-stores/default/controls", tags=["control-stores"])

_logger = get_logger(__name__)

_CONTROL_NAME_UNIQUE_CONSTRAINTS = {
    "controls_name_key",
    "idx_controls_name_active",
}


def _serialize_control_data(
    control_data: ControlDefinition | UnrenderedTemplateControl,
) -> dict[str, object]:
    """Serialize control data for JSONB storage."""
    data_json = control_data.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
        exclude_unset=True,
    )
    if "scope" in data_json and isinstance(data_json["scope"], dict):
        data_json["scope"] = {
            k: v for k, v in data_json["scope"].items() if v is not None
        }
    # Always persist enabled explicitly so _enabled_from_stored_payload reads
    # the correct value (especially for unrendered templates where enabled=False).
    if "enabled" not in data_json:
        data_json["enabled"] = control_data.enabled
    return data_json


def _is_template_backed_payload(data: object) -> bool:
    """Return whether stored control JSON contains template metadata."""
    return isinstance(data, dict) and data.get("template") is not None


def _is_unrendered_template(data: object) -> bool:
    """Return whether stored control JSON is an unrendered template."""
    return (
        isinstance(data, dict)
        and data.get("template") is not None
        and data.get("condition") is None
    )


def _parse_stored_control_data(
    data: dict[str, object],
    *,
    control_name: str,
    control_id: int,
) -> ControlDefinition | UnrenderedTemplateControl:
    """Parse stored JSONB into the appropriate model type."""
    if _is_unrendered_template(data):
        try:
            return UnrenderedTemplateControl.model_validate(data)
        except ValidationError:
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
            )

    return parse_control_definition_or_api_error(
        data,
        detail=f"Control '{control_name}' has invalid data",
        hint=f"Update the control data using PUT /api/v1/controls/{control_id}/data.",
        field_prefix=None,
    )


def _enabled_from_stored_payload(data: object) -> bool:
    """Return the persisted enabled flag, defaulting to True when absent."""
    if not isinstance(data, dict):
        return True
    raw_enabled = data.get("enabled", True)
    return raw_enabled if type(raw_enabled) is bool else True


def _control_description_from_data(data: dict[str, object]) -> str | None:
    """Return a human-friendly control description from stored JSON."""
    template = data.get("template")
    template_description = template.get("description") if isinstance(template, dict) else None
    description = data.get("description")
    return cast(str | None, description or template_description)


def _control_scope_from_data(data: dict[str, object]) -> dict[str, object]:
    """Return the stored scope object when present."""
    raw_scope = data.get("scope")
    return raw_scope if isinstance(raw_scope, dict) else {}


def _build_control_summary(
    control_id: int,
    name: str,
    data: dict[str, object],
    *,
    usage: AgentRef | None,
    used_by_agents_count: int,
) -> ControlSummary:
    """Build the admin control-browse summary from stored JSON."""
    scope = _control_scope_from_data(data)
    return ControlSummary(
        id=control_id,
        name=name,
        description=_control_description_from_data(data),
        enabled=_enabled_from_stored_payload(data),
        execution=cast(str | None, data.get("execution")),
        step_types=cast(list[str] | None, scope.get("step_types")),
        stages=cast(list[str] | None, scope.get("stages")),
        tags=cast(list[str], data.get("tags", [])),
        template_backed="template" in data,
        template_rendered=("condition" in data if "template" in data else None),
        used_by_agent=usage,
        used_by_agents_count=used_by_agents_count,
    )


def _build_published_control_summary(
    control_id: int,
    name: str,
    data: dict[str, object],
    *,
    published_at: dt.datetime,
) -> PublishedControlSummary:
    """Build the published-store summary from stored JSON."""
    scope = _control_scope_from_data(data)
    return PublishedControlSummary(
        id=control_id,
        name=name,
        description=_control_description_from_data(data),
        enabled=_enabled_from_stored_payload(data),
        execution=cast(str | None, data.get("execution")),
        step_types=cast(list[str] | None, scope.get("step_types")),
        stages=cast(list[str] | None, scope.get("stages")),
        tags=cast(list[str], data.get("tags", [])),
        template_backed="template" in data,
        template_rendered=("condition" in data if "template" in data else None),
        published_at=published_at.isoformat(),
    )


def _published_control_conflict(control_id: int, *, action: str) -> ConflictError:
    """Return the standard conflict for published controls on runtime paths."""
    return ConflictError(
        error_code=ErrorCode.CONTROL_PUBLISHED,
        detail=(
            f"Control with ID '{control_id}' is published in the Control Store and "
            f"cannot be used for runtime {action}"
        ),
        resource="Control",
        resource_id=str(control_id),
        hint="Clone the published control first, then associate the clone.",
        errors=[
            ValidationErrorItem(
                resource="Control",
                field="control_id",
                code="published_control_conflict",
                message="Published controls must be cloned before runtime association.",
                value=control_id,
            )
        ],
    )


def _template_backed_raw_update_conflict(control_id: int) -> ConflictError:
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


def _is_control_name_conflict(error: IntegrityError) -> bool:
    """Return whether an IntegrityError came from the active-control name uniqueness guard."""
    diag = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if diag in _CONTROL_NAME_UNIQUE_CONSTRAINTS:
        return True

    error_text = " ".join(
        part for part in (str(error.orig), str(error)) if part and part != "None"
    )
    return any(name in error_text for name in _CONTROL_NAME_UNIQUE_CONSTRAINTS)


async def _render_and_validate_template_input(
    template_input: TemplateControlInput,
    *,
    db: AsyncSession,
    enabled: bool = True,
) -> ControlDefinition:
    """Render a template-backed input and validate evaluator config."""
    rendered = render_template_control_input(template_input, enabled=enabled)
    try:
        await _validate_control_definition(rendered.control, db)
    except APIValidationError as exc:
        raise remap_template_api_error(
            exc,
            reverse_path_map=rendered.reverse_path_map,
            template=template_input.template,
        ) from exc
    return rendered.control


async def _materialize_control_input(
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
                True if current_payload is None else _enabled_from_stored_payload(current_payload)
            )
            return await _render_and_validate_template_input(
                control_input,
                db=db,
                enabled=enabled,
            )

        # Incomplete values — only allowed for new controls or already-unrendered
        # templates.  Updating a rendered control with incomplete values is
        # rejected to prevent silently stripping rendered fields.
        current_is_rendered = (
            current_payload is not None
            and isinstance(current_payload, dict)
            and current_payload.get("condition") is not None
        )
        if current_is_rendered:
            # Force a full render attempt so the caller gets a clear error
            # about which required parameters are missing.
            enabled = _enabled_from_stored_payload(current_payload)
            return await _render_and_validate_template_input(
                control_input,
                db=db,
                enabled=enabled,
            )

        validate_template_structure(control_input.template)
        validate_partial_template_values(
            control_input.template, control_input.template_values,
        )
        return UnrenderedTemplateControl(
            template=control_input.template,
            template_values=dict(control_input.template_values),
            enabled=False,
        )

    if current_payload is not None and _is_template_backed_payload(current_payload):
        if control_id is None:
            raise RuntimeError("control_id is required for template-backed raw updates")
        raise _template_backed_raw_update_conflict(control_id)

    await _validate_control_definition(control_input, db)
    return control_input


async def _validate_control_definition(
    control_def: ControlDefinition, db: AsyncSession
) -> None:
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
                agent_result = await db.execute(
                    select(Agent).where(Agent.name == agent_namespace)
                )
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
                except ValidationError as e:
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
                            for err in e.errors()
                        ],
                    ) from e
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
                except JSONSchemaValidationError:
                    raise APIValidationError(
                        error_code=ErrorCode.INVALID_CONFIG,
                        detail=f"Config validation failed for evaluator '{evaluator_ref}'",
                        resource="Control",
                        hint=(
                            "Check the evaluator's config schema for required fields and types."
                        ),
                        errors=[
                            ValidationErrorItem(
                                resource="Control",
                                field=f"{field_prefix}.evaluator.config",
                                code="schema_validation_error",
                                message=_SCHEMA_VALIDATION_FAILED_MESSAGE,
                            )
                        ],
                    )
            continue

        evaluator_cls = available_evaluators.get(parsed.name)
        if evaluator_cls is None:
            # Global (builtin / external) evaluators may be absent from this runtime
            # (optional packages, forward compatibility). Store the definition without
            # config validation; evaluation will fail later if the evaluator is missing.
            continue

        try:
            evaluator_cls.config_model(**evaluator_spec.config)
        except ValidationError as e:
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
                    for err in e.errors()
                ],
            )
        except TypeError:
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
            )


@template_router.post(
    "/render",
    response_model=RenderControlTemplateResponse,
    response_model_exclude_none=True,
    summary="Render a control template preview",
    response_description="Rendered control preview",
)
async def render_control_template(
    request: RenderControlTemplateRequest,
    db: AsyncSession = Depends(get_async_db),
) -> RenderControlTemplateResponse:
    """Render a template-backed control without persisting it."""
    control_def = await _render_and_validate_template_input(
        TemplateControlInput(
            template=request.template,
            template_values=request.template_values,
        ),
        db=db,
        enabled=True,
    )
    return RenderControlTemplateResponse(control=control_def)


@router.put(
    "",
    dependencies=[Depends(require_admin_key)],
    response_model=CreateControlResponse,
    summary="Create a new control",
    response_description="Created control ID",
)
async def create_control(
    request: CreateControlRequest, db: AsyncSession = Depends(get_async_db)
) -> CreateControlResponse:
    """
    Create a new control with a unique name.

    Controls define protection logic and can be added to policies.
    Control data is required and is validated before anything is inserted.

    Args:
        request: Control creation request with unique name and data
        db: Database session (injected)

    Returns:
        CreateControlResponse with the new control's ID

    Raises:
        HTTPException 409: Control with this name already exists
        HTTPException 500: Database error during creation
    """
    control_service = ControlService(db)

    # Uniqueness check
    if await control_service.active_control_name_exists(request.name):
        raise ConflictError(
            error_code=ErrorCode.CONTROL_NAME_CONFLICT,
            detail=f"Control with name '{request.name}' already exists",
            resource="Control",
            resource_id=request.name,
            hint="Choose a different name or update the existing control.",
        )

    control_def = await _materialize_control_input(request.data, db=db)
    control_data = _serialize_control_data(control_def)

    control = control_service.create_control(name=request.name, data=control_data)
    try:
        await control_service.create_version(
            control,
            event_type="created",
            note="Initial creation",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_control_name_conflict(exc):
            raise ConflictError(
                error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                detail=f"Control with name '{request.name}' already exists",
                resource="Control",
                resource_id=request.name,
                hint="Choose a different name or update the existing control.",
            )
        _logger.error(
            "Failed to create control '%s' due to integrity error",
            request.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to create control '{request.name}': database error",
            resource="Control",
            operation="create",
        )
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to create control '{request.name}'",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to create control '{request.name}': database error",
            resource="Control",
            operation="create",
        )
    return CreateControlResponse(control_id=control.id)


@router.get(
    "/schema",
    response_model=GetControlSchemaResponse,
    summary="Get control definition JSON schema",
    response_description="JSON schema for ControlDefinition",
)
async def get_control_schema() -> GetControlSchemaResponse:
    """Return the canonical JSON schema for ControlDefinition."""
    return GetControlSchemaResponse(
        schema=ControlDefinition.model_json_schema(by_alias=True)
    )


@router.get(
    "/{control_id}",
    response_model=GetControlResponse,
    summary="Get control details",
    response_description="Control metadata and configuration",
)
async def get_control(
    control_id: int, db: AsyncSession = Depends(get_async_db)
) -> GetControlResponse:
    """
    Retrieve a control by ID including its name and configuration data.

    Args:
        control_id: ID of the control
        db: Database session (injected)

    Returns:
        GetControlResponse with control id, name, and data

    Raises:
        HTTPException 404: Control not found
    """
    control = await ControlService(db).get_active_control_or_404(control_id)
    control_data = _parse_stored_control_data(
        control.data,
        control_name=control.name,
        control_id=control_id,
    )

    return GetControlResponse(
        id=control.id,
        name=control.name,
        data=control_data,
    )


@router.get(
    "/{control_id}/data",
    response_model=GetControlDataResponse,
    response_model_exclude_none=True,
    summary="Get control configuration data",
    response_description="Control data payload",
)
async def get_control_data(
    control_id: int, db: AsyncSession = Depends(get_async_db)
) -> GetControlDataResponse:
    """
    Retrieve the configuration data for a control.

    Control data is a JSONB field that must follow the ControlDefinition schema.

    Args:
        control_id: ID of the control
        db: Database session (injected)

    Returns:
        GetControlDataResponse with validated ControlDefinition

    Raises:
        HTTPException 404: Control not found
        HTTPException 422: Control data is corrupted
    """
    control = await ControlService(db).get_active_control_or_404(control_id)
    control_data = _parse_stored_control_data(
        control.data,
        control_name=control.name,
        control_id=control_id,
    )
    return GetControlDataResponse(data=control_data)


@router.get(
    "/{control_id}/versions",
    response_model=ListControlVersionsResponse,
    summary="List control version history",
    response_description="Paginated control version summaries",
)
async def list_control_versions(
    control_id: int,
    cursor: int | None = Query(
        None, description="Version number to start after (newest-first pagination)"
    ),
    limit: int = Query(_DEFAULT_PAGINATION_LIMIT, ge=1, le=_MAX_PAGINATION_LIMIT),
    db: AsyncSession = Depends(get_async_db),
) -> ListControlVersionsResponse:
    """List control versions ordered newest-first using cursor-based pagination."""
    page = await ControlService(db).list_versions(control_id, cursor=cursor, limit=limit)

    return ListControlVersionsResponse(
        versions=[
            ControlVersionSummary(
                version_num=version.version_num,
                event_type=version.event_type,
                note=version.note,
                created_at=version.created_at.isoformat(),
            )
            for version in page.versions
        ],
        pagination=PaginationInfo(
            limit=limit,
            total=page.total,
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        ),
    )


@router.get(
    "/{control_id}/versions/{version_num}",
    response_model=GetControlVersionResponse,
    summary="Get a specific control version",
    response_description="Full control version snapshot",
)
async def get_control_version(
    control_id: int,
    version_num: int,
    db: AsyncSession = Depends(get_async_db),
) -> GetControlVersionResponse:
    """Return a specific control version, including its raw persisted snapshot."""
    version = await ControlService(db).get_version_or_404(control_id, version_num)
    return GetControlVersionResponse(
        version_num=version.version_num,
        event_type=version.event_type,
        note=version.note,
        created_at=version.created_at.isoformat(),
        snapshot=version.snapshot,
    )


@router.put(
    "/{control_id}/data",
    dependencies=[Depends(require_admin_key)],
    response_model=SetControlDataResponse,
    summary="Update control configuration data",
    response_description="Success confirmation",
)
async def set_control_data(
    control_id: int,
    request: SetControlDataRequest,
    db: AsyncSession = Depends(get_async_db),
) -> SetControlDataResponse:
    """
    Update the configuration data for a control.

    This replaces the entire data payload. The data is validated against
    the ControlDefinition schema.

    Args:
        control_id: ID of the control
        request: New control data (replaces existing)
        db: Database session (injected)

    Returns:
        SetControlDataResponse with success flag

    Raises:
        HTTPException 404: Control not found
        HTTPException 500: Database error during update
    """
    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(control_id, for_update=True)

    control_def = await _materialize_control_input(
        request.data,
        db=db,
        current_payload=control.data,
        control_id=control_id,
    )

    control_service.replace_control_data(
        control,
        data=_serialize_control_data(control_def),
    )
    control_name = control.name
    try:
        await control_service.create_version(
            control,
            event_type="updated",
            note="Edited",
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to update data for control '{control_name}' ({control_id})",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to update data for control '{control_name}': database error",
            resource="Control",
            operation="update data",
        )
    return SetControlDataResponse(success=True)


@router.post(
    "/validate",
    response_model=ValidateControlDataResponse,
    summary="Validate control configuration",
    response_description="Validation result",
)
async def validate_control_data(
    request: ValidateControlDataRequest, db: AsyncSession = Depends(get_async_db)
) -> ValidateControlDataResponse:
    """
    Validate control configuration data without saving it.

    Args:
        request: Control configuration data to validate
        db: Database session (injected)

    Returns:
        ValidateControlDataResponse with success=True if valid
    """
    # Validate mirrors create: complete template values trigger a full render,
    # incomplete values validate structure only (matching unrendered create).
    await _materialize_control_input(request.data, db=db)
    return ValidateControlDataResponse(success=True)


@router.get(
    "",
    response_model=ListControlsResponse,
    summary="List all controls",
    response_description="Paginated list of controls",
)
async def list_controls(
    cursor: int | None = Query(None, description="Control ID to start after"),
    limit: int = Query(_DEFAULT_PAGINATION_LIMIT, ge=1, le=_MAX_PAGINATION_LIMIT),
    name: str | None = Query(None, description="Filter by name (partial, case-insensitive)"),
    enabled: bool | None = Query(None, description="Filter by enabled status"),
    template_backed: bool | None = Query(
        None,
        description="Filter by whether the control is template-backed",
    ),
    step_type: str | None = Query(
        None, description="Filter by step type (built-ins: 'tool', 'llm')"
    ),
    stage: str | None = Query(None, description="Filter by stage ('pre' or 'post')"),
    execution: str | None = Query(None, description="Filter by execution ('server' or 'sdk')"),
    tag: str | None = Query(None, description="Filter by tag"),
    db: AsyncSession = Depends(get_async_db),
) -> ListControlsResponse:
    """
    List all controls with optional filtering and cursor-based pagination.

    Controls are returned ordered by ID descending (newest first).

    Args:
        cursor: ID of the last control from the previous page (for pagination)
        limit: Maximum number of controls to return (default 20, max 100)
        name: Optional filter by name (partial, case-insensitive match)
        enabled: Optional filter by enabled status
        template_backed: Optional filter by whether the control is template-backed
        step_type: Optional filter by step type (built-ins: 'tool', 'llm')
        stage: Optional filter by stage ('pre' or 'post')
        execution: Optional filter by execution ('server' or 'sdk')
        tag: Optional filter by tag
        db: Database session (injected)

    Returns:
        ListControlsResponse with control summaries and pagination info

    Example:
        GET /controls?limit=10&enabled=true&step_type=tool
    """
    control_service = ControlService(db)
    page = await control_service.list_controls_page(
        cursor=cursor,
        limit=limit,
        name=name,
        enabled=enabled,
        template_backed=template_backed,
        step_type=step_type,
        stage=stage,
        execution=execution,
        tag=tag,
    )
    usage_by_control_id = await control_service.list_control_usage(
        [control.id for control in page.controls]
    )

    # Build summaries (filtering already done at DB level)
    summaries: list[ControlSummary] = []
    for ctrl in page.controls:
        data = ctrl.data or {}
        usage = usage_by_control_id.get(ctrl.id)
        summaries.append(
            _build_control_summary(
                ctrl.id,
                ctrl.name,
                data,
                usage=(
                    AgentRef(agent_name=usage.representative_agent_name)
                    if usage is not None and usage.representative_agent_name is not None
                    else None
                ),
                used_by_agents_count=usage.used_by_agents_count if usage is not None else 0,
            )
        )

    return ListControlsResponse(
        controls=summaries,
        pagination=PaginationInfo(
            limit=limit,
            total=page.total,
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        ),
    )


@store_router.post(
    "/{control_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=AssocResponse,
    summary="Publish a control to the default store",
    response_description="Success confirmation",
)
async def publish_control(
    control_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> AssocResponse:
    """Publish an active, valid, runtime-unassociated control to the default store."""
    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(control_id, for_update=True)
    control_name = control.name
    _parse_stored_control_data(
        control.data,
        control_name=control_name,
        control_id=control.id,
    )

    associations = await control_service.list_control_associations(control_id)
    if associations.policy_ids or associations.agent_names:
        raise ConflictError(
            error_code=ErrorCode.CONTROL_IN_USE,
            detail=(
                f"Control '{control.name}' is already associated with "
                f"{len(associations.policy_ids)} policy/policies and "
                f"{len(associations.agent_names)} agent(s)"
            ),
            resource="Control",
            resource_id=str(control_id),
            hint=(
                "Published controls must not have runtime associations. "
                "Clone them for runtime use."
            ),
        )

    try:
        await control_service.publish_control(control_id)
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to publish control '%s' (%s) to the default store",
            control_name,
            control_id,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to publish control '{control_name}': database error",
            resource="Control",
            operation="publish",
        )

    return AssocResponse(success=True)


@store_router.delete(
    "/{control_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=AssocResponse,
    summary="Unpublish a control from the default store",
    response_description="Success confirmation",
)
async def unpublish_control(
    control_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> AssocResponse:
    """Remove a control from the default store idempotently."""
    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(control_id, for_update=True)
    control_name = control.name

    try:
        await control_service.unpublish_control(control_id)
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to unpublish control '%s' (%s) from the default store",
            control_name,
            control_id,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to unpublish control '{control_name}': database error",
            resource="Control",
            operation="unpublish",
        )

    return AssocResponse(success=True)


@store_router.get(
    "",
    dependencies=[Depends(require_admin_key)],
    response_model=ListPublishedControlsResponse,
    summary="Browse controls published in the default store",
    response_description="Paginated published control summaries",
)
async def list_published_controls(
    cursor: int | None = Query(
        None,
        description="Control ID cursor from the previous page",
    ),
    limit: int = Query(_DEFAULT_PAGINATION_LIMIT, ge=1, le=_MAX_PAGINATION_LIMIT),
    name: str | None = Query(None, description="Filter by name (partial, case-insensitive)"),
    enabled: bool | None = Query(None, description="Filter by enabled status"),
    tag: str | None = Query(None, description="Filter by tag"),
    db: AsyncSession = Depends(get_async_db),
) -> ListPublishedControlsResponse:
    """List default-store controls ordered by publication time descending."""
    try:
        page = await ControlService(db).list_published_controls_page(
            cursor=cursor,
            limit=limit,
            name=name,
            enabled=enabled,
            tag=tag,
        )
    except (OperationalError, ProgrammingError, RuntimeError):
        _logger.error(
            "Failed to list published controls from the default store",
            exc_info=True,
        )
        raise DatabaseError(
            detail="Failed to list published controls: database error",
            resource="ControlStore",
            operation="list",
        )

    return ListPublishedControlsResponse(
        controls=[
            _build_published_control_summary(
                published.control.id,
                published.control.name,
                published.control.data,
                published_at=published.published_at,
            )
            for published in page.controls
        ],
        pagination=PaginationInfo(
            limit=limit,
            total=page.total,
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        ),
    )


@router.post(
    "/{control_id}/clone",
    dependencies=[Depends(require_admin_key)],
    response_model=CloneControlResponse,
    summary="Clone a control",
    response_description="Cloned control metadata",
)
async def clone_control(
    control_id: int,
    request: CloneControlRequest | None = None,
    db: AsyncSession = Depends(get_async_db),
) -> CloneControlResponse:
    """Clone an active control into a new independent control with provenance."""
    max_auto_name_retries = 5
    control_service = ControlService(db)
    source_control = await control_service.get_active_control_or_404(control_id, for_update=True)
    _parse_stored_control_data(
        source_control.data,
        control_name=source_control.name,
        control_id=source_control.id,
    )

    requested_name = request.name if request is not None else None
    if (
        requested_name is not None
        and await control_service.active_control_name_exists(requested_name)
    ):
        raise ConflictError(
            error_code=ErrorCode.CONTROL_NAME_CONFLICT,
            detail=f"Control with name '{requested_name}' already exists",
            resource="Control",
            resource_id=requested_name,
            hint="Choose a different name or update the existing control.",
        )

    source_name = source_control.name
    auto_name_attempts = 0

    while True:
        target_name = (
            requested_name
            if requested_name is not None
            else await control_service.generate_unique_clone_name(source_control.name)
        )
        try:
            cloned_control = await control_service.clone_control(
                source_control=source_control,
                name=target_name,
            )
            await db.commit()
            break
        except IntegrityError as exc:
            await db.rollback()
            if _is_control_name_conflict(exc):
                if requested_name is not None:
                    raise ConflictError(
                        error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                        detail=f"Control with name '{target_name}' already exists",
                        resource="Control",
                        resource_id=target_name,
                        hint="Choose a different name or update the existing control.",
                    )
                auto_name_attempts += 1
                if auto_name_attempts >= max_auto_name_retries:
                    raise ConflictError(
                        error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                        detail=f"Failed to generate a unique clone name for '{source_name}'",
                        resource="Control",
                        resource_id=str(control_id),
                        hint="Retry the clone request or provide an explicit name.",
                    )
                source_control = await control_service.get_active_control_or_404(
                    control_id,
                    for_update=True,
                )
                _parse_stored_control_data(
                    source_control.data,
                    control_name=source_control.name,
                    control_id=source_control.id,
                )
                source_name = source_control.name
                continue
            _logger.error(
                "Failed to clone control '%s' (%s) due to integrity error",
                source_name,
                control_id,
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to clone control '{source_name}': database error",
                resource="Control",
                operation="clone",
            )
        except Exception:
            await db.rollback()
            _logger.error(
                "Failed to clone control '%s' (%s)",
                source_name,
                control_id,
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to clone control '{source_name}': database error",
                resource="Control",
                operation="clone",
            )

    return CloneControlResponse(
        control_id=cloned_control.id,
        name=cloned_control.name,
        cloned_control_id=source_control.id,
    )


@router.delete(
    "/{control_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=DeleteControlResponse,
    summary="Delete a control",
    response_description="Deletion confirmation with dissociation info",
)
async def delete_control(
    control_id: int,
    force: bool = Query(
        False,
        description="If true, dissociate from all policy/agent links before deleting. "
        "If false, fail if control is associated with any policy or agent.",
    ),
    db: AsyncSession = Depends(get_async_db),
) -> DeleteControlResponse:
    """
    Delete a control by ID.

    By default, deletion fails if the control is associated with any policy or agent.
    Use force=true to automatically dissociate and delete.

    Args:
        control_id: ID of the control to delete
        force: If true, remove associations before deleting
        db: Database session (injected)

    Returns:
        DeleteControlResponse with success flag and dissociation details

    Raises:
        HTTPException 404: Control not found
        HTTPException 409: Control is in use (and force=false)
        HTTPException 500: Database error during deletion
    """
    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(control_id, for_update=True)

    associations = await control_service.list_control_associations(control_id)
    associated_policy_ids = associations.policy_ids
    associated_agent_names = associations.agent_names

    if (associated_policy_ids or associated_agent_names) and not force:
        errors = [
            ValidationErrorItem(
                resource="Policy",
                field="controls",
                code="control_in_use",
                message=f"Control is associated with policy ID {pid}",
                value=pid,
            )
            for pid in associated_policy_ids
        ] + [
            ValidationErrorItem(
                resource="Agent",
                field="controls",
                code="control_in_use",
                message=f"Control is directly associated with agent '{agent_name}'",
                value=agent_name,
            )
            for agent_name in associated_agent_names
        ]
        raise ConflictError(
            error_code=ErrorCode.CONTROL_IN_USE,
            detail=(
                f"Control '{control.name}' is associated with "
                f"{len(associated_policy_ids)} policy/policies and "
                f"{len(associated_agent_names)} agent(s)"
            ),
            resource="Control",
            resource_id=control.name,
            hint="Use force=true to dissociate and delete, or remove associations manually first.",
            errors=errors,
        )

    # Remove associations if force=true.
    dissociated_from_policies: list[int] = []
    dissociated_from_agents: list[str] = []
    if associated_policy_ids or associated_agent_names:
        dissociated = await control_service.remove_all_control_associations(control_id)
        dissociated_from_policies = dissociated.policy_ids
        dissociated_from_agents = dissociated.agent_names
    if dissociated_from_policies or dissociated_from_agents:
        _logger.info(
            "Dissociated control '%s' (%s) from %s policy/policies and %s agent(s)",
            control.name,
            control_id,
            len(dissociated_from_policies),
            len(dissociated_from_agents),
        )

    # Tombstone the control so backfilled version history remains referentially intact.
    control_service.mark_control_deleted(control, deleted_at=dt.datetime.now(dt.UTC))
    control_name = control.name
    try:
        await control_service.remove_all_store_publications(control_id)
        await control_service.create_version(
            control,
            event_type="deleted",
            note="Deleted",
        )
        await db.commit()
        _logger.info("Soft-deleted control '%s' (%s)", control.name, control_id)
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to soft-delete control '{control_name}' ({control_id})",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to delete control '{control_name}': database error",
            resource="Control",
            operation="delete",
        )

    return DeleteControlResponse(
        success=True,
        dissociated_from=dissociated_from_policies,
        dissociated_from_policies=dissociated_from_policies,
        dissociated_from_agents=dissociated_from_agents,
    )


@router.patch(
    "/{control_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=PatchControlResponse,
    summary="Update control metadata",
    response_description="Updated control information",
)
async def patch_control(
    control_id: int,
    request: PatchControlRequest,
    db: AsyncSession = Depends(get_async_db),
) -> PatchControlResponse:
    """
    Update control metadata (name and/or enabled status).

    This endpoint allows partial updates:
    - To rename: provide 'name' field
    - To enable/disable: provide 'enabled' field (updates the control's data)

    Args:
        control_id: ID of the control to update
        request: Fields to update (name, enabled)
        db: Database session (injected)

    Returns:
        PatchControlResponse with current control state

    Raises:
        HTTPException 404: Control not found
        HTTPException 409: New name conflicts with existing control
        HTTPException 422: Cannot update metadata for corrupted control data
        HTTPException 500: Database error during update
    """
    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(control_id, for_update=True)
    parsed_control = _parse_stored_control_data(
        control.data,
        control_name=control.name,
        control_id=control_id,
    )

    # Track if anything changed
    updated = False

    # Update name if provided
    if request.name is not None and request.name != control.name:
        # Check for name collision
        if await control_service.active_control_name_exists(
            request.name,
            exclude_control_id=control_id,
        ):
            raise ConflictError(
                error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                detail=f"Control with name '{request.name}' already exists",
                resource="Control",
                resource_id=request.name,
                hint="Choose a different name or update the existing control.",
            )
        control_service.rename_control(control, name=request.name)
        updated = True

    # Update enabled status if provided
    current_enabled: bool | None = None
    if request.enabled is not None:
        if isinstance(parsed_control, UnrenderedTemplateControl):
            if request.enabled:
                raise APIValidationError(
                    error_code=ErrorCode.VALIDATION_ERROR,
                    detail=(
                        f"Cannot enable control '{control.name}': "
                        "unrendered template controls must be rendered first"
                    ),
                    resource="Control",
                    hint=(
                        "Provide complete parameter values via "
                        f"PUT /api/v1/controls/{control_id}/data "
                        "to render the template before enabling."
                    ),
                    errors=[
                        ValidationErrorItem(
                            resource="Control",
                            field="enabled",
                            code="unrendered_template_cannot_enable",
                            message=(
                                "Provide parameter values to render "
                                "the template before enabling."
                            ),
                        )
                    ],
                )
            # enabled=False on an unrendered template is a no-op (already false).
            current_enabled = False
        else:
            if parsed_control.enabled != request.enabled:
                control_service.set_control_enabled(control, enabled=request.enabled)
                updated = True
            current_enabled = request.enabled if updated else parsed_control.enabled
    else:
        current_enabled = parsed_control.enabled

    # Commit if anything changed
    if updated:
        attempted_control_name = control.name
        try:
            await control_service.create_version(
                control,
                event_type="updated",
                note="Edited",
            )
            await db.commit()
            _logger.info(f"Updated control '{control.name}' ({control_id})")
        except IntegrityError as exc:
            await db.rollback()
            if _is_control_name_conflict(exc):
                conflicting_name = request.name or control.name
                raise ConflictError(
                    error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                    detail=f"Control with name '{conflicting_name}' already exists",
                    resource="Control",
                    resource_id=conflicting_name,
                    hint="Choose a different name or update the existing control.",
                )
            _logger.error(
                "Failed to update control '%s' (%s) due to integrity error",
                attempted_control_name,
                control_id,
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to update control '{attempted_control_name}': database error",
                resource="Control",
                operation="update",
            )
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to update control '{attempted_control_name}' ({control_id})",
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to update control '{attempted_control_name}': database error",
                resource="Control",
                operation="update",
            )

    return PatchControlResponse(
        success=True,
        name=control.name,
        enabled=current_enabled,
    )
