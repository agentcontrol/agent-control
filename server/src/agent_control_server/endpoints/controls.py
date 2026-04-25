import datetime as dt

from agent_control_models import ControlDefinition, TemplateControlInput, UnrenderedTemplateControl
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
    AgentRef,
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
    PaginationInfo,
    PatchControlRequest,
    PatchControlResponse,
    RenderControlTemplateRequest,
    RenderControlTemplateResponse,
    RestoreControlVersionResponse,
    SetControlDataRequest,
    SetControlDataResponse,
    ValidateControlDataRequest,
    ValidateControlDataResponse,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..db import get_async_db
from ..errors import (
    APIError,
    APIValidationError,
    ConflictError,
    DatabaseError,
)
from ..logging_utils import get_logger
from ..services.control_data_validation import (
    materialize_control_input,
    normalize_control_data_for_response,
    parse_stored_control_data,
    render_and_validate_template_input,
    serialize_control_data,
)
from ..services.controls import ControlService

# Pagination constants
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100

router = APIRouter(prefix="/controls", tags=["controls"])
template_router = APIRouter(prefix="/control-templates", tags=["controls"])

_logger = get_logger(__name__)

_CONTROL_NAME_UNIQUE_CONSTRAINTS = {
    "controls_name_key",
    "idx_controls_name_active",
}


def _is_control_name_conflict(error: IntegrityError) -> bool:
    """Return whether an IntegrityError came from the active-control name uniqueness guard."""
    diag = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if diag in _CONTROL_NAME_UNIQUE_CONSTRAINTS:
        return True

    error_text = " ".join(
        part for part in (str(error.orig), str(error)) if part and part != "None"
    )
    return any(name in error_text for name in _CONTROL_NAME_UNIQUE_CONSTRAINTS)


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
    control_def = await render_and_validate_template_input(
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

    control_def = await materialize_control_input(request.data, db=db)
    control_data = serialize_control_data(control_def)

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
    return GetControlSchemaResponse(schema=ControlDefinition.model_json_schema(by_alias=True))


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
        GetControlResponse with control id, name, and canonical validated data

    Raises:
        HTTPException 404: Control not found
    """
    control = await ControlService(db).get_active_control_or_404(control_id)
    control_data = parse_stored_control_data(
        control.data,
        control_name=control.name,
        control_id=control_id,
    )

    return GetControlResponse(
        id=control.id,
        name=control.name,
        data=normalize_control_data_for_response(
            control.data,
            parsed_data=control_data,
        ),
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
        GetControlDataResponse with canonical validated control data

    Raises:
        HTTPException 404: Control not found
        HTTPException 422: Control data is corrupted
    """
    control = await ControlService(db).get_active_control_or_404(control_id)
    control_data = parse_stored_control_data(
        control.data,
        control_name=control.name,
        control_id=control_id,
    )
    return GetControlDataResponse(
        data=normalize_control_data_for_response(
            control.data,
            parsed_data=control_data,
        )
    )


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


@router.post(
    "/{control_id}/versions/{version_num}/restore",
    dependencies=[Depends(require_admin_key)],
    response_model=RestoreControlVersionResponse,
    response_model_exclude_none=True,
    summary="Restore a control version",
    response_description="Restored control state and current version number",
)
async def restore_control_version(
    control_id: int,
    version_num: int,
    db: AsyncSession = Depends(get_async_db),
) -> RestoreControlVersionResponse:
    """Restore an active control to a historical version in one atomic write."""
    control_service = ControlService(db)
    try:
        result = await control_service.restore_version(control_id, version_num)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_control_name_conflict(exc):
            raise ConflictError(
                error_code=ErrorCode.CONTROL_NAME_CONFLICT,
                detail="Restored control name conflicts with another active control",
                resource="Control",
                resource_id=str(control_id),
                hint="Choose another version or rename the conflicting control.",
            )
        _logger.error(
            "Failed to restore control '%s' from version '%s' due to integrity error",
            control_id,
            version_num,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to restore control '{control_id}': database error",
            resource="Control",
            operation="restore",
        )
    except APIError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to restore control '%s' from version '%s'",
            control_id,
            version_num,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to restore control '{control_id}': database error",
            resource="Control",
            operation="restore",
        )

    control_data = parse_stored_control_data(
        result.control.data,
        control_name=result.control.name,
        control_id=control_id,
    )
    return RestoreControlVersionResponse(
        success=True,
        control_id=control_id,
        restored_from_version_num=result.restored_from_version_num,
        current_version_num=result.current_version_num,
        name=result.control.name,
        data=normalize_control_data_for_response(
            result.control.data,
            parsed_data=control_data,
        ),
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

    control_def = await materialize_control_input(
        request.data,
        db=db,
        current_payload=control.data,
        control_id=control_id,
    )
    serialized_control_data = serialize_control_data(control_def)

    if control.data == serialized_control_data:
        return SetControlDataResponse(success=True)

    control_service.replace_control_data(
        control,
        data=serialized_control_data,
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
    await materialize_control_input(request.data, db=db)
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
        # Extract summary fields from JSONB data
        data = ctrl.data or {}
        scope = data.get("scope") or {}
        usage = usage_by_control_id.get(ctrl.id)
        summaries.append(
            ControlSummary(
                id=ctrl.id,
                name=ctrl.name,
                description=(
                    data.get("description") or (data.get("template") or {}).get("description")
                ),
                enabled=data.get("enabled", True),
                execution=data.get("execution"),
                step_types=scope.get("step_types"),
                stages=scope.get("stages"),
                tags=data.get("tags", []),
                template_backed="template" in data,
                template_rendered=("condition" in data if "template" in data else None),
                used_by_agent=(
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
    parsed_control = parse_stored_control_data(
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
                                "Provide parameter values to render the template before enabling."
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
