"""Evaluator discovery endpoints."""

from typing import Any

from agent_control_engine import list_evaluators
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/evaluators", tags=["evaluators"])


class EvaluatorInfo(BaseModel):
    """Information about a registered evaluator."""

    name: str = Field(..., description="Evaluator name")
    version: str = Field(..., description="Evaluator version")
    description: str = Field(..., description="Evaluator description")
    requires_api_key: bool = Field(..., description="Whether evaluator requires API key")
    timeout_ms: int = Field(..., description="Default timeout in milliseconds")
    config_schema: dict[str, Any] = Field(..., description="JSON Schema for config")


@router.get(
    "",
    response_model=dict[str, EvaluatorInfo],
    summary="List available evaluators",
    response_description="Dictionary of evaluator name to evaluator info",
)
async def get_evaluators() -> dict[str, EvaluatorInfo]:
    """List all available evaluators.

    Returns metadata and JSON Schema for each built-in evaluator.

    Built-in evaluators:
    - **regex**: Regular expression pattern matching
    - **list**: List-based value matching with flexible logic
    - **json**: JSON validation with schema, types, constraints
    - **sql**: SQL query validation

    Custom evaluators are registered per-agent via initAgent.
    Use GET /agents/{agent_id}/evaluators to list agent-specific schemas.
    """
    evaluators = list_evaluators()

    return {
        name: EvaluatorInfo(
            name=evaluator_cls.metadata.name,
            version=evaluator_cls.metadata.version,
            description=evaluator_cls.metadata.description,
            requires_api_key=evaluator_cls.metadata.requires_api_key,
            timeout_ms=evaluator_cls.metadata.timeout_ms,
            config_schema=evaluator_cls.config_model.model_json_schema(),
        )
        for name, evaluator_cls in evaluators.items()
    }
