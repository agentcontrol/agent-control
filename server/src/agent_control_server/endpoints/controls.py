import jsonschema
from agent_control_models import get_plugin
from agent_control_models.server import (
    CreateControlRequest,
    CreateControlResponse,
    GetControlDataResponse,
    SetControlDataRequest,
    SetControlDataResponse,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..logging_utils import get_logger
from ..models import Control
from ..services.evaluators import get_evaluator_by_name

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

    Controls define protection logic and can be added to control sets.
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
        raise HTTPException(
            status_code=409,
            detail=f"Control with name '{request.name}' already exists",
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
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create control '{request.name}': database error",
        )
    return CreateControlResponse(control_id=control.id)


@router.get(
    "/{control_id}/data",
    response_model=GetControlDataResponse,
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
        GetControlDataResponse with control data dictionary

    Raises:
        HTTPException 404: Control not found
    """
    res = await db.execute(select(Control).where(Control.id == control_id))
    control = res.scalars().first()
    if control is None:
        raise HTTPException(
            status_code=404, detail=f"Control with ID '{control_id}' not found"
        )
    return GetControlDataResponse(data=control.data)


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
        raise HTTPException(
            status_code=404, detail=f"Control with ID '{control_id}' not found"
        )

    # Validate custom evaluator config against its schema
    plugin_name = request.data.evaluator.plugin
    if get_plugin(plugin_name) is None:
        # Not a built-in plugin - check if it's a custom evaluator
        custom_eval = await get_evaluator_by_name(plugin_name, db)
        if custom_eval is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown plugin '{plugin_name}'. Register it via PUT /evaluators first.",
            )
        # Validate user_config against the custom evaluator's schema
        if custom_eval.config_schema:
            user_config = request.data.evaluator.config.get("user_config", {})
            try:
                jsonschema.validate(user_config, custom_eval.config_schema)
            except jsonschema.ValidationError as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Config validation failed for '{plugin_name}': {e.message}",
                )

    control.data = request.data.model_dump(mode="json")
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to update data for control '{control.name}' ({control_id})",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update data for control '{control.name}': database error",
        )
    return SetControlDataResponse(success=True)
