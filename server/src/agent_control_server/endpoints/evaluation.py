"""Evaluation analysis endpoints."""

from typing import Any

from agent_control_engine.core import ControlEngine
from agent_control_models import (
    ControlDefinition,
    EvaluationRequest,
    EvaluationResponse,
    get_plugin,
)
from agent_control_plugins.dynamic import register_custom_evaluator
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..logging_utils import get_logger
from ..services.controls import list_controls_for_agent
from ..services.evaluators import list_custom_evaluators

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

_logger = get_logger(__name__)


class ControlAdapter:
    """Adapts API Control to Engine ControlWithIdentity protocol."""

    def __init__(self, id: int, name: str, control_data: dict[str, Any]):
        self.id = id
        self.name = name
        self.control = ControlDefinition.model_validate(control_data)


@router.post(
    "",
    response_model=EvaluationResponse,
    summary="Analyze content safety",
    response_description="Safety analysis result",
)
async def evaluate(
    request: EvaluationRequest,
    db: AsyncSession = Depends(get_async_db)
) -> EvaluationResponse:
    """Analyze content for safety and control violations."""
    # 1. Ensure custom evaluators are registered
    custom_evaluators = await list_custom_evaluators(db)
    for ce in custom_evaluators:
        if get_plugin(ce.name) is None:
            register_custom_evaluator(
                name=ce.name,
                code=ce.code,
                description=ce.description,
                entrypoint=ce.entrypoint,
                timeout_ms=ce.timeout_ms,
                config_schema=ce.config_schema,
            )

    # 2. Fetch controls for the agent
    api_controls = await list_controls_for_agent(request.agent_uuid, db)

    # 3. Adapt controls for the engine
    engine_controls = []
    for c in api_controls:
        try:
            engine_controls.append(ControlAdapter(c.id, c.name, c.control))
        except Exception as e:
            _logger.warning(f"Failed to adapt control '{c.name}': {e}")
            continue

    # 4. Execute Control Engine (async for plugin support)
    engine = ControlEngine(engine_controls)
    try:
        return await engine.process_async(request)
    except ValueError as e:
        # Handle unknown plugin or invalid config errors
        _logger.error(f"Evaluation failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))
