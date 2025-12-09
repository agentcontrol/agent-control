"""Custom evaluator management endpoints."""

from typing import Any

from agent_control_models import get_plugin
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..services.evaluators import (
    create_or_update_evaluator,
    delete_evaluator,
    get_evaluator_by_name,
    is_evaluator_in_use,
    list_custom_evaluators,
)

router = APIRouter(prefix="/evaluators", tags=["evaluators"])


# Built-in plugin names that cannot be used for custom evaluators
RESERVED_PLUGIN_NAMES = {"regex", "list"}


class CreateEvaluatorRequest(BaseModel):
    """Request to create or update a custom evaluator."""

    name: str = Field(..., min_length=1, max_length=255, description="Unique evaluator name")
    code: str = Field(
        ..., min_length=1, description="Python code with evaluate(data, config) function"
    )
    config_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema defining the config structure",
    )
    description: str | None = Field(None, max_length=1000, description="Optional description")
    entrypoint: str = Field("evaluate", description="Function name to call")
    timeout_ms: int = Field(5000, ge=100, le=60000, description="Timeout in milliseconds")


class EvaluatorResponse(BaseModel):
    """Response after creating/updating an evaluator."""

    evaluator_id: int
    name: str


class EvaluatorDetailResponse(BaseModel):
    """Detailed evaluator information."""

    id: int
    name: str
    description: str | None
    code: str
    config_schema: dict[str, Any]
    entrypoint: str
    timeout_ms: int
    created_at: str
    updated_at: str


class EvaluatorListItem(BaseModel):
    """Evaluator summary for list response."""

    id: int
    name: str
    description: str | None
    config_schema: dict[str, Any]


@router.put(
    "",
    response_model=EvaluatorResponse,
    summary="Register or update a custom evaluator",
    response_description="Created/updated evaluator info",
)
async def put_evaluator(
    request: CreateEvaluatorRequest,
    db: AsyncSession = Depends(get_async_db),
) -> EvaluatorResponse:
    """Register a new custom evaluator or update an existing one.

    Custom evaluators allow you to define evaluation logic as Python code.
    Once registered, they can be referenced by name in Controls, just like
    built-in plugins (regex, list).

    The code must define a function matching the entrypoint (default: "evaluate")
    with signature: `def evaluate(data, config) -> EvaluatorResult`

    - `data`: The data extracted by the Control's selector
    - `config`: The config dict provided in the Control's evaluator config

    Example code:
    ```python
    def evaluate(data, config):
        target = config["target"]
        if target in str(data):
            return EvaluatorResult(matched=True, confidence=1.0, message="Found")
        return EvaluatorResult(matched=False, confidence=1.0, message="Clean")
    ```
    """
    # Validate name doesn't conflict with built-in plugins
    if request.name in RESERVED_PLUGIN_NAMES:
        raise HTTPException(
            status_code=409,
            detail=f"Name '{request.name}' conflicts with built-in plugin",
        )

    # Check if it conflicts with any other registered plugin
    existing_plugin = get_plugin(request.name)
    if existing_plugin is not None:
        # Check if it's a custom evaluator we're updating (OK) or a built-in (conflict)
        existing_custom = await get_evaluator_by_name(request.name, db)
        if existing_custom is None:
            # It's a built-in plugin, conflict
            raise HTTPException(
                status_code=409,
                detail=f"Name '{request.name}' conflicts with existing plugin",
            )

    # Validate code compiles
    try:
        compile(request.code, filename="<custom-evaluator>", mode="exec")
    except SyntaxError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Code syntax error: {e}",
        )

    evaluator = await create_or_update_evaluator(
        name=request.name,
        code=request.code,
        config_schema=request.config_schema,
        db=db,
        description=request.description,
        entrypoint=request.entrypoint,
        timeout_ms=request.timeout_ms,
    )

    return EvaluatorResponse(evaluator_id=evaluator.id, name=evaluator.name)


@router.get(
    "",
    response_model=list[EvaluatorListItem],
    summary="List all custom evaluators",
    response_description="List of custom evaluators",
)
async def list_evaluators(
    db: AsyncSession = Depends(get_async_db),
) -> list[EvaluatorListItem]:
    """List all registered custom evaluators.

    Returns evaluator metadata including config_schema for each.
    Does not include the code - use GET /evaluators/{name} for full details.
    """
    evaluators = await list_custom_evaluators(db)
    return [
        EvaluatorListItem(
            id=e.id,
            name=e.name,
            description=e.description,
            config_schema=e.config_schema,
        )
        for e in evaluators
    ]


@router.get(
    "/{name}",
    response_model=EvaluatorDetailResponse,
    summary="Get custom evaluator details",
    response_description="Full evaluator details including code",
)
async def get_evaluator(
    name: str,
    db: AsyncSession = Depends(get_async_db),
) -> EvaluatorDetailResponse:
    """Get full details of a custom evaluator including its code."""
    evaluator = await get_evaluator_by_name(name, db)
    if evaluator is None:
        raise HTTPException(status_code=404, detail=f"Evaluator '{name}' not found")

    return EvaluatorDetailResponse(
        id=evaluator.id,
        name=evaluator.name,
        description=evaluator.description,
        code=evaluator.code,
        config_schema=evaluator.config_schema,
        entrypoint=evaluator.entrypoint,
        timeout_ms=evaluator.timeout_ms,
        created_at=evaluator.created_at.isoformat(),
        updated_at=evaluator.updated_at.isoformat(),
    )


@router.delete(
    "/{name}",
    status_code=204,
    summary="Delete a custom evaluator",
    response_description="No content on success",
)
async def remove_evaluator(
    name: str,
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Delete a custom evaluator.

    Fails with 409 Conflict if the evaluator is currently in use by any Control.
    """
    # Check if exists
    evaluator = await get_evaluator_by_name(name, db)
    if evaluator is None:
        raise HTTPException(status_code=404, detail=f"Evaluator '{name}' not found")

    # Check if in use
    if await is_evaluator_in_use(name, db):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete evaluator '{name}' - it is in use by one or more Controls",
        )

    await delete_evaluator(name, db)
