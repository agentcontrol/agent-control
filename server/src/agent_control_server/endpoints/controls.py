from agent_control_engine import list_evaluators
from agent_control_models import ControlDefinition
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
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
)
from fastapi import APIRouter, Depends, Query
from jsonschema_rs import ValidationError as JSONSchemaValidationError
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..errors import (
    APIValidationError,
    ConflictError,
    DatabaseError,
    NotFoundError,
)
from ..logging_utils import get_logger
from ..models import Agent, AgentData, Control, policy_controls
from ..services.evaluator_utils import parse_evaluator_ref, validate_config_against_schema

# Pagination constants
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100

router = APIRouter(prefix="/controls", tags=["controls"])

_logger = get_logger(__name__)


@router.put(
    "",
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
        except ValidationError as e:
            # Data exists but is corrupted - log and return None
            _logger.warning(
                "Control '%s' (id=%s) has corrupted data that failed validation: %s",
                control.name,
                control_id,
                str(e),
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

    # Validate evaluator config
    evaluator_ref = request.data.evaluator.name
    agent_name, eval_name = parse_evaluator_ref(evaluator_ref)

    if agent_name is not None:
        # Agent-scoped evaluator: validate against agent's registered schema
        agent_result = await db.execute(
            select(Agent).where(Agent.name == agent_name)
        )
        agent = agent_result.scalars().first()
        if agent is None:
            raise NotFoundError(
                error_code=ErrorCode.AGENT_NOT_FOUND,
                detail=f"Agent '{agent_name}' not found",
                resource="Agent",
                resource_id=agent_name,
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
                detail=f"Agent '{agent_name}' has invalid data",
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
            (e for e in (agent_data.evaluators or []) if e.name == eval_name),
            None,
        )
        if evaluator is None:
            available = [e.name for e in (agent_data.evaluators or [])]
            raise APIValidationError(
                error_code=ErrorCode.EVALUATOR_NOT_FOUND,
                detail=f"Evaluator '{eval_name}' is not registered with agent '{agent_name}'",
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
                        message=f"Evaluator '{eval_name}' not found on agent '{agent_name}'",
                        value=evaluator_ref,
                    )
                ],
            )

        # Validate config against evaluator's schema
        if evaluator.config_schema:
            try:
                validate_config_against_schema(
                    request.data.evaluator.config, evaluator.config_schema
                )
            except JSONSchemaValidationError as e:
                raise APIValidationError(
                    error_code=ErrorCode.INVALID_CONFIG,
                    detail=f"Config validation failed for evaluator '{agent_name}:{eval_name}'",
                    resource="Control",
                    hint="Check the evaluator's config schema for required fields and types.",
                    errors=[
                        ValidationErrorItem(
                            resource="Control",
                            field="data.evaluator.config",
                            code="schema_validation_error",
                            message=e.message,
                        )
                    ],
                )
    else:
        # Built-in or server-side evaluator: validate if registered
        evaluator_cls = list_evaluators().get(eval_name)
        if evaluator_cls is not None:
            try:
                evaluator_cls.config_model(**request.data.evaluator.config)
            except ValidationError as e:
                raise APIValidationError(
                    error_code=ErrorCode.INVALID_CONFIG,
                    detail=f"Config validation failed for evaluator '{eval_name}'",
                    resource="Control",
                    hint="Check the evaluator's config schema for required fields and types.",
                    errors=[
                        ValidationErrorItem(
                            resource="Control",
                            field=(
                                f"data.evaluator.config."
                                f"{'.'.join(str(loc) for loc in err.get('loc', []))}"
                            ),
                            code=err.get("type", "validation_error"),
                            message=err.get("msg", "Validation failed"),
                        )
                        for err in e.errors()
                    ],
                )
            except TypeError as e:
                raise APIValidationError(
                    error_code=ErrorCode.INVALID_CONFIG,
                    detail=f"Invalid config parameters for evaluator '{eval_name}'",
                    resource="Control",
                    hint="Check the evaluator's config schema for valid parameter names.",
                    errors=[
                        ValidationErrorItem(
                            resource="Control",
                            field="data.evaluator.config",
                            code="invalid_parameters",
                            message=str(e),
                        )
                    ],
                )
        # If evaluator not found, allow it - might be a server-side registered evaluator
        # that will be validated at runtime

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
    # Get total count (with filters applied)
    count_query = select(func.count()).select_from(Control)
    query = select(Control).order_by(Control.id.desc())

    # Apply cursor
    if cursor is not None:
        query = query.where(Control.id < cursor)
        count_query = count_query.where(Control.id < cursor)

    # Apply name filter (case-insensitive partial match)
    if name is not None:
        query = query.where(Control.name.ilike(f"%{name}%"))
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
        total_query = total_query.where(Control.name.ilike(f"%{name}%"))
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
    response_model=DeleteControlResponse,
    summary="Delete a control",
    response_description="Deletion confirmation with dissociation info",
)
async def delete_control(
    control_id: int,
    force: bool = Query(
        False,
        description="If true, dissociate from all policies before deleting. "
        "If false, fail if control is associated with any policy.",
    ),
    db: AsyncSession = Depends(get_async_db),
) -> DeleteControlResponse:
    """
    Delete a control by ID.

    By default, deletion fails if the control is associated with any policy.
    Use force=true to automatically dissociate and delete.

    Args:
        control_id: ID of the control to delete
        force: If true, remove associations before deleting
        db: Database session (injected)

    Returns:
        DeleteControlResponse with success flag and list of dissociated policies

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

    # Check for associations with policies
    assoc_result = await db.execute(
        select(policy_controls.c.policy_id).where(
            policy_controls.c.control_id == control_id
        )
    )
    associated_policy_ids = [row[0] for row in assoc_result.all()]

    if associated_policy_ids and not force:
        raise ConflictError(
            error_code=ErrorCode.CONTROL_IN_USE,
            detail=(
                f"Control '{control.name}' is associated with "
                f"{len(associated_policy_ids)} policy/policies"
            ),
            resource="Control",
            resource_id=control.name,
            hint="Use force=true to dissociate and delete, or remove associations manually first.",
            errors=[
                ValidationErrorItem(
                    resource="Policy",
                    field="controls",
                    code="control_in_use",
                    message=f"Control is associated with policy ID {pid}",
                    value=pid,
                )
                for pid in associated_policy_ids
            ],
        )

    # Remove associations if force=true
    dissociated_from: list[int] = []
    if associated_policy_ids:
        await db.execute(
            delete(policy_controls).where(
                policy_controls.c.control_id == control_id
            )
        )
        dissociated_from = associated_policy_ids
        _logger.info(
            f"Dissociated control '{control.name}' ({control_id}) "
            f"from {len(dissociated_from)} policy/policies"
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

    return DeleteControlResponse(success=True, dissociated_from=dissociated_from)


@router.patch(
    "/{control_id}",
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
        except ValidationError as e:
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
                        message=str(e),
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
