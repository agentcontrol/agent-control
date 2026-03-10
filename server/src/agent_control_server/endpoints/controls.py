from agent_control_engine import list_evaluators
from agent_control_models import ControlDefinition
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
    AgentRef,
    ControlSummary,
    CreateControlRequest,
    CreateControlResponse,
    DeleteControlResponse,
    GetControlDataResponse,
    GetControlResponse,
    ListControlsResponse,
    PaginationInfo,
    PatchControlRequest,
    PatchControlResponse,
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
from ..services.evaluator_utils import (
    parse_evaluator_ref_full,
    validate_config_against_schema,
)
from ..services.query_utils import escape_like_pattern

# Pagination constants
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100
_INVALID_PARAMETERS_MESSAGE = "Invalid config parameters for evaluator."
_CORRUPTED_CONTROL_DATA_MESSAGE = "Stored control data is corrupted and cannot be parsed."
_SCHEMA_VALIDATION_FAILED_MESSAGE = "Config does not satisfy the evaluator schema."

router = APIRouter(prefix="/controls", tags=["controls"])

_logger = get_logger(__name__)


async def _validate_control_definition(
    control_def: ControlDefinition, db: AsyncSession
) -> None:
    """Validate evaluator config for a control definition."""
    evaluator_ref = control_def.evaluator.name
    parsed = parse_evaluator_ref_full(evaluator_ref)

    if parsed.type == "agent":
        # Agent-scoped evaluator: validate against agent's registered schema
        agent_result = await db.execute(
            select(Agent).where(Agent.name == parsed.namespace)
        )
        agent = agent_result.scalars().first()
        if agent is None:
            raise NotFoundError(
                error_code=ErrorCode.AGENT_NOT_FOUND,
                detail=f"Agent '{parsed.namespace}' not found",
                resource="Agent",
                resource_id=parsed.namespace,
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
                        field=".".join(str(loc) for loc in err.get("loc", [])),
                        code=err.get("type", "validation_error"),
                        message=err.get("msg", "Validation failed"),
                    )
                    for err in e.errors()
                ],
            )

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
                    f"with agent '{parsed.namespace}'"
                ),
                resource="Evaluator",
                hint=(
                    f"Register it via initAgent first. "
                    f"Available evaluators: {available or 'none'}."
                ),
                errors=[
                    ValidationErrorItem(
                        resource="Control",
                        field="data.evaluator.name",
                        code="evaluator_not_found",
                        message=(
                            f"Evaluator '{parsed.local_name}' not found "
                            f"on agent '{parsed.namespace}'"
                        ),
                        value=evaluator_ref,
                    )
                ],
            )

        # Validate config against evaluator's schema
        if evaluator.config_schema:
            try:
                validate_config_against_schema(
                    control_def.evaluator.config, evaluator.config_schema
                )
            except JSONSchemaValidationError:
                raise APIValidationError(
                    error_code=ErrorCode.INVALID_CONFIG,
                    detail=f"Config validation failed for evaluator '{evaluator_ref}'",
                    resource="Control",
                    hint="Check the evaluator's config schema for required fields and types.",
                    errors=[
                        ValidationErrorItem(
                            resource="Control",
                            field="data.evaluator.config",
                            code="schema_validation_error",
                            message=_SCHEMA_VALIDATION_FAILED_MESSAGE,
                        )
                    ],
                )
    else:
        # Built-in or external evaluator: validate if registered
        evaluator_cls = list_evaluators().get(parsed.name)
        if evaluator_cls is not None:
            try:
                evaluator_cls.config_model(**control_def.evaluator.config)
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
                                "data.evaluator.config."
                                f"{'.'.join(str(loc) for loc in err.get('loc', []))}"
                            ),
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
                            field="data.evaluator.config",
                            code="invalid_parameters",
                            message=_INVALID_PARAMETERS_MESSAGE,
                        )
                    ],
                )
        # If evaluator not found, allow it - might be a server-side registered evaluator


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
    Create a new control with a unique name and empty data.

    Controls define protection logic and can be added to policies.
    Use the PUT /{control_id}/data endpoint to set control configuration.

    Args:
        request: Control creation request with unique name
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

    control = Control(name=request.name, data={})
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
    control_data: ControlDefinition | None = None
    if control.data:
        try:
            control_data = ControlDefinition.model_validate(control.data)
        except ValidationError:
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
    try:
        control_def = ControlDefinition.model_validate(control.data)
    except ValidationError as e:
        raise APIValidationError(
            error_code=ErrorCode.CORRUPTED_DATA,
            detail=f"Control '{control.name}' has invalid data",
            resource="Control",
            hint="Update the control data using PUT /{control_id}/data.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field=".".join(str(loc) for loc in err.get("loc", [])),
                    code=err.get("type", "validation_error"),
                    message=err.get("msg", "Validation failed"),
                )
                for err in e.errors()
            ],
        )
    return GetControlDataResponse(data=control_def)


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

    # Validate evaluator config using shared logic
    await _validate_control_definition(request.data, db)

    data_json = request.data.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    # Pydantic's exclude_none doesn't propagate into nested model dicts after
    # serialization, so we re-dump the selector separately to strip null keys.
    try:
        selector_json = request.data.selector.model_dump(exclude_none=True, exclude_unset=True)  # type: ignore[attr-defined]
        selector_json = {k: v for k, v in selector_json.items() if v is not None}
        if selector_json:
            data_json["selector"] = selector_json
    except AttributeError:
        # Selector doesn't support model_dump, use original serialization
        pass
    # Ensure scope does not store null/None for step_names or other optional fields,
    # so round-trip (save then load) preserves step selection in the UI.
    if "scope" in data_json and isinstance(data_json["scope"], dict):
        data_json["scope"] = {
            k: v for k, v in data_json["scope"].items() if v is not None
        }
    control.data = data_json
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
    await _validate_control_definition(request.data, db)
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
                description=data.get("description"),
                enabled=data.get("enabled", True),
                execution=data.get("execution"),
                step_types=scope.get("step_types"),
                stages=scope.get("stages"),
                tags=data.get("tags", []),
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
        try:
            ctrl_def = ControlDefinition.model_validate(control.data)
            current_enabled = ctrl_def.enabled
        except ValidationError:
            # Data corrupted, use default enabled=True
            _logger.warning("Control '%s' has invalid data, using default", control.name)

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
