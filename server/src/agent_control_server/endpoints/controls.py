from agent_control_engine import list_evaluators
from agent_control_models import ControlDefinition, TemplateControlInput, UnrenderedTemplateControl
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
    AgentRef,
    ControlSummary,
    CreateControlRequest,
    CreateControlResponse,
    DeleteControlResponse,
    GetControlDataResponse,
    GetControlResponse,
    GetControlSchemaResponse,
    ListControlsResponse,
    PaginationInfo,
    PatchControlRequest,
    PatchControlResponse,
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
from sqlalchemy import Integer, String, delete, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
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
from ..models import Agent, AgentData, Control, agent_controls, agent_policies, policy_controls
from ..services.condition_traversal import iter_condition_leaves_with_paths
from ..services.control_definitions import parse_control_definition_or_api_error
from ..services.control_templates import (
    can_render_template,
    remap_template_api_error,
    render_template_control_input,
    validate_partial_template_values,
    validate_template_structure,
)
from ..services.evaluator_utils import (
    parse_evaluator_ref_full,
    validate_config_against_schema,
)
from ..services.query_utils import escape_like_pattern
from ..services.validation_paths import format_field_path

# Pagination constants
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100
_INVALID_PARAMETERS_MESSAGE = "Invalid config parameters for evaluator."
_CORRUPTED_CONTROL_DATA_MESSAGE = "Stored control data is corrupted and cannot be parsed."
_SCHEMA_VALIDATION_FAILED_MESSAGE = "Config does not satisfy the evaluator schema."

router = APIRouter(prefix="/controls", tags=["controls"])
template_router = APIRouter(prefix="/control-templates", tags=["controls"])

_logger = get_logger(__name__)


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
    # Uniqueness check
    existing = await db.execute(select(Control.id).where(Control.name == request.name))
    if existing.first() is not None:
        raise ConflictError(
            error_code=ErrorCode.CONTROL_NAME_CONFLICT,
            detail=f"Control with name '{request.name}' already exists",
            resource="Control",
            resource_id=request.name,
            hint="Choose a different name or update the existing control.",
        )

    control_def = await _materialize_control_input(request.data, db=db)
    control_data = _serialize_control_data(control_def)

    control = Control(name=request.name, data=control_data)
    db.add(control)
    try:
        await db.commit()
        await db.refresh(control)
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            error_code=ErrorCode.CONTROL_NAME_CONFLICT,
            detail=f"Control with name '{request.name}' already exists",
            resource="Control",
            resource_id=request.name,
            hint="Choose a different name or update the existing control.",
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
    res = await db.execute(select(Control).where(Control.id == control_id))
    control = res.scalars().first()
    if control is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )

    # Parse data if present and non-empty
    control_data: ControlDefinition | UnrenderedTemplateControl | None = None
    if control.data:
        try:
            control_data = _parse_stored_control_data(
                control.data,
                control_name=control.name,
                control_id=control_id,
            )
        except Exception:
            # Data exists but is corrupted - log and return None
            _logger.warning(
                "Control '%s' (id=%s) has corrupted data that failed validation",
                control.name,
                control_id,
                exc_info=True,
            )
            control_data = None

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
    res = await db.execute(select(Control).where(Control.id == control_id))
    control = res.scalars().first()
    if control is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )
    control_data = _parse_stored_control_data(
        control.data,
        control_name=control.name,
        control_id=control_id,
    )
    return GetControlDataResponse(data=control_data)


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
    res = await db.execute(select(Control).where(Control.id == control_id))
    control = res.scalars().first()
    if control is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )

    control_def = await _materialize_control_input(
        request.data,
        db=db,
        current_payload=control.data,
        control_id=control_id,
    )

    control.data = _serialize_control_data(control_def)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to update data for control '{control.name}' ({control_id})",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to update data for control '{control.name}': database error",
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
    query = select(Control).order_by(Control.id.desc())

    # Apply cursor
    if cursor is not None:
        query = query.where(Control.id < cursor)

    # Apply name filter (case-insensitive partial match)
    if name is not None:
        query = query.where(Control.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\"))
        # Don't apply to count_query - total should be pre-filter

    # Apply JSONB filters at database level
    if enabled is not None:
        if enabled:
            # enabled=True: include if enabled is true OR key doesn't exist (default is True)
            query = query.where(
                or_(
                    Control.data["enabled"].astext == "true",
                    ~Control.data.has_key("enabled"),
                )
            )
        else:
            # enabled=False: only include if explicitly false
            query = query.where(Control.data["enabled"].astext == "false")

    if template_backed is not None:
        if template_backed:
            query = query.where(Control.data.has_key("template"))
        else:
            query = query.where(~Control.data.has_key("template"))

    # Filters that reference rendered-only fields exclude unrendered templates
    # (which lack condition/execution/scope/tags).
    has_rendered_filter = any(f is not None for f in (step_type, stage, execution, tag))
    if has_rendered_filter:
        query = query.where(Control.data.has_key("condition"))

    if step_type is not None:
        query = query.where(
            or_(
                Control.data["scope"]["step_types"].contains([step_type]),
                ~Control.data.has_key("scope"),
                ~Control.data["scope"].has_key("step_types"),
            )
        )
    if stage is not None:
        query = query.where(
            or_(
                Control.data["scope"]["stages"].contains([stage]),
                ~Control.data.has_key("scope"),
                ~Control.data["scope"].has_key("stages"),
            )
        )
    if execution is not None:
        query = query.where(Control.data["execution"].astext == execution)

    if tag is not None:
        query = query.where(Control.data["tags"].contains([tag]))

    # Fetch limit + 1 to check for more pages
    query = query.limit(limit + 1)
    result = await db.execute(query)
    controls = list(result.scalars().all())

    # Get total count (with same filters, but without cursor/limit)
    total_query = select(func.count()).select_from(Control)
    if name is not None:
        total_query = total_query.where(
            Control.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\")
        )
    if enabled is not None:
        if enabled:
            total_query = total_query.where(
                or_(
                    Control.data["enabled"].astext == "true",
                    ~Control.data.has_key("enabled"),
                )
            )
        else:
            total_query = total_query.where(Control.data["enabled"].astext == "false")
    if template_backed is not None:
        if template_backed:
            total_query = total_query.where(Control.data.has_key("template"))
        else:
            total_query = total_query.where(~Control.data.has_key("template"))
    if has_rendered_filter:
        total_query = total_query.where(Control.data.has_key("condition"))
    if step_type is not None:
        total_query = total_query.where(
            or_(
                Control.data["scope"]["step_types"].contains([step_type]),
                ~Control.data.has_key("scope"),
                ~Control.data["scope"].has_key("step_types"),
            )
        )
    if stage is not None:
        total_query = total_query.where(
            or_(
                Control.data["scope"]["stages"].contains([stage]),
                ~Control.data.has_key("scope"),
                ~Control.data["scope"].has_key("stages"),
            )
        )
    if execution is not None:
        total_query = total_query.where(Control.data["execution"].astext == execution)
    if tag is not None:
        total_query = total_query.where(Control.data["tags"].contains([tag]))
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    # Check if there are more pages
    has_more = len(controls) > limit
    if has_more:
        controls = controls[:-1]

    # Build mapping of control_id -> usage attribution
    # Traversal includes both:
    # - Control -> policy_controls -> agent_policies -> Agent
    # - Control -> agent_controls -> Agent
    control_agent_map: dict[int, AgentRef | None] = {ctrl.id: None for ctrl in controls}
    control_agent_names_map: dict[int, set[str]] = {ctrl.id: set() for ctrl in controls}
    control_agent_repr_map: dict[int, str | None] = {ctrl.id: None for ctrl in controls}
    if controls:
        control_ids = [ctrl.id for ctrl in controls]
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
        agents_query = union_all(policy_agents_query, direct_agents_query)
        agents_result = await db.execute(agents_query)
        for row in agents_result.all():
            control_id, agent_name = row
            control_agent_names_map[control_id].add(agent_name)

            # Keep a deterministic representative agent for backwards compatibility.
            current_repr = control_agent_repr_map[control_id]
            if current_repr is None or agent_name < current_repr:
                control_agent_repr_map[control_id] = agent_name
                control_agent_map[control_id] = AgentRef(
                    agent_name=agent_name
                )

    # Build summaries (filtering already done at DB level)
    summaries: list[ControlSummary] = []
    for ctrl in controls:
        # Extract summary fields from JSONB data
        data = ctrl.data or {}
        scope = data.get("scope") or {}
        summaries.append(
            ControlSummary(
                id=ctrl.id,
                name=ctrl.name,
                description=(
                    data.get("description")
                    or (data.get("template") or {}).get("description")
                ),
                enabled=data.get("enabled", True),
                execution=data.get("execution"),
                step_types=scope.get("step_types"),
                stages=scope.get("stages"),
                tags=data.get("tags", []),
                template_backed="template" in data,
                template_rendered=(
                    "condition" in data if "template" in data else None
                ),
                used_by_agent=control_agent_map.get(ctrl.id),
                used_by_agents_count=len(control_agent_names_map.get(ctrl.id, set())),
            )
        )

    # Determine next cursor
    next_cursor: str | None = None
    if has_more and controls:
        next_cursor = str(controls[-1].id)

    return ListControlsResponse(
        controls=summaries,
        pagination=PaginationInfo(
            limit=limit,
            total=total,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
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
    # Find the control
    result = await db.execute(select(Control).where(Control.id == control_id))
    control = result.scalars().first()
    if control is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )

    # Check for associations with policies and direct agent links.
    policy_assoc_query = select(
        policy_controls.c.policy_id.label("policy_id"),
        literal(None, type_=String).label("agent_name"),
    ).where(policy_controls.c.control_id == control_id)
    agent_assoc_query = select(
        literal(None, type_=Integer).label("policy_id"),
        agent_controls.c.agent_name.label("agent_name"),
    ).where(agent_controls.c.control_id == control_id)
    assoc_result = await db.execute(union_all(policy_assoc_query, agent_assoc_query))

    associated_policy_ids: list[int] = []
    associated_agent_names: list[str] = []
    for policy_id, agent_name in assoc_result.all():
        if policy_id is not None:
            associated_policy_ids.append(policy_id)
        if agent_name is not None:
            associated_agent_names.append(agent_name)

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
    if associated_policy_ids:
        await db.execute(delete(policy_controls).where(policy_controls.c.control_id == control_id))
        dissociated_from_policies = associated_policy_ids
    if associated_agent_names:
        await db.execute(delete(agent_controls).where(agent_controls.c.control_id == control_id))
        dissociated_from_agents = associated_agent_names
    if dissociated_from_policies or dissociated_from_agents:
        _logger.info(
            "Dissociated control '%s' (%s) from %s policy/policies and %s agent(s)",
            control.name,
            control_id,
            len(dissociated_from_policies),
            len(dissociated_from_agents),
        )

    # Delete the control
    await db.delete(control)
    try:
        await db.commit()
        _logger.info(f"Deleted control '{control.name}' ({control_id})")
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to delete control '{control.name}' ({control_id})",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to delete control '{control.name}': database error",
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
        HTTPException 422: Cannot update enabled status (control has no data configured)
        HTTPException 500: Database error during update
    """
    # Find the control
    result = await db.execute(select(Control).where(Control.id == control_id))
    control = result.scalars().first()
    if control is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )

    # Track if anything changed
    updated = False

    # Update name if provided
    if request.name is not None and request.name != control.name:
        # Check for name collision
        existing = await db.execute(
            select(Control.id).where(Control.name == request.name)
        )
        if existing.first() is not None:
            raise ConflictError(
                error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                detail=f"Control with name '{request.name}' already exists",
                resource="Control",
                resource_id=request.name,
                hint="Choose a different name or update the existing control.",
            )
        control.name = request.name
        updated = True

    # Update enabled status if provided
    current_enabled: bool | None = None
    if request.enabled is not None:
        if not control.data:
            raise APIValidationError(
                error_code=ErrorCode.VALIDATION_ERROR,
                detail=(
                    f"Cannot update enabled status: control '{control.name}' "
                    "has no data configured"
                ),
                resource="Control",
                hint=f"Use PUT /{control_id}/data to configure the control first.",
                errors=[
                    ValidationErrorItem(
                        resource="Control",
                        field="enabled",
                        code="no_data_configured",
                        message="Control must have data configured before enabling/disabling",
                    )
                ],
            )

        if _is_unrendered_template(control.data):
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
            try:
                ctrl_def = ControlDefinition.model_validate(control.data)
                if ctrl_def.enabled != request.enabled:
                    new_data = dict(control.data)
                    new_data["enabled"] = request.enabled
                    control.data = new_data
                    updated = True
                current_enabled = request.enabled if updated else ctrl_def.enabled
            except ValidationError:
                _logger.error(
                    "Control '%s' (%s) has corrupted data in patch request",
                    control.name,
                    control_id,
                    exc_info=True,
                )
                raise APIValidationError(
                    error_code=ErrorCode.CORRUPTED_DATA,
                    detail=f"Control '{control.name}' has corrupted data",
                    resource="Control",
                    hint="Update the control data using PUT /{control_id}/data.",
                    errors=[
                        ValidationErrorItem(
                            resource="Control",
                            field="data",
                            code="corrupted_data",
                            message=_CORRUPTED_CONTROL_DATA_MESSAGE,
                        )
                    ],
                )
    elif control.data:
        # Get current enabled status for response
        if _is_unrendered_template(control.data):
            current_enabled = False
        else:
            try:
                ctrl_def = ControlDefinition.model_validate(control.data)
                current_enabled = ctrl_def.enabled
            except ValidationError:
                _logger.warning(
                    "Control '%s' has invalid data, using default",
                    control.name,
                )

    # Commit if anything changed
    if updated:
        try:
            await db.commit()
            _logger.info(f"Updated control '{control.name}' ({control_id})")
        except IntegrityError:
            await db.rollback()
            conflicting_name = request.name or control.name
            raise ConflictError(
                error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                detail=f"Control with name '{conflicting_name}' already exists",
                resource="Control",
                resource_id=conflicting_name,
                hint="Choose a different name or update the existing control.",
            )
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to update control '{control.name}' ({control_id})",
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to update control '{control.name}': database error",
                resource="Control",
                operation="update",
            )

    return PatchControlResponse(
        success=True,
        name=control.name,
        enabled=current_enabled,
    )
