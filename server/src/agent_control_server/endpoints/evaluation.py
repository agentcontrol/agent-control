"""Evaluation analysis endpoints."""

from agent_control_engine.core import ControlEngine
from agent_control_models import (
    ControlDefinition,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
)
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import RequireAPIKey
from ..db import get_async_db
from ..errors import APIValidationError, NotFoundError
from ..logging_utils import get_logger
from ..models import Agent
from ..services.controls import list_controls_for_agent

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

_logger = get_logger(__name__)

SAFE_EVALUATOR_ERROR = "Evaluation failed due to an internal evaluator error."
SAFE_EVALUATOR_TIMEOUT_ERROR = "Evaluation timed out before completion."
SAFE_INVALID_STEP_REGEX_ERROR = "Control configuration error: invalid step name regex."
SAFE_ENGINE_VALIDATION_MESSAGE = "Invalid evaluation request or control configuration."


class ControlAdapter:
    """Adapts API Control to Engine ControlWithIdentity protocol."""

    def __init__(self, id: int, name: str, control: ControlDefinition):
        self.id = id
        self.name = name
        self.control = control


def _sanitize_evaluator_error(error_message: str) -> str:
    """Convert evaluator runtime errors into safe client-facing text."""
    if "invalid step_name_regex" in error_message.lower():
        return SAFE_INVALID_STEP_REGEX_ERROR
    if "timeout" in error_message.lower():
        return SAFE_EVALUATOR_TIMEOUT_ERROR
    return SAFE_EVALUATOR_ERROR


def _sanitize_condition_trace(trace: object) -> object:
    """Recursively redact internal evaluator errors from condition traces."""
    if isinstance(trace, list):
        return [_sanitize_condition_trace(item) for item in trace]

    if not isinstance(trace, dict):
        return trace

    sanitized = {
        key: _sanitize_condition_trace(value)
        for key, value in trace.items()
    }

    raw_error = sanitized.get("error")
    if isinstance(raw_error, str) and raw_error:
        safe_error = _sanitize_evaluator_error(raw_error)
        sanitized["error"] = safe_error
        raw_message = sanitized.get("message")
        if raw_message is None or isinstance(raw_message, str):
            sanitized["message"] = safe_error

    return sanitized


def _sanitize_control_match(match: ControlMatch) -> ControlMatch:
    """Redact internal evaluator error strings from a control match."""
    if match.result.error is None:
        return match

    safe_error = _sanitize_evaluator_error(match.result.error)
    safe_message = safe_error
    metadata = dict(match.result.metadata or {})
    condition_trace = metadata.get("condition_trace")
    if condition_trace is not None:
        metadata["condition_trace"] = _sanitize_condition_trace(condition_trace)
    sanitized_result = match.result.model_copy(
        update={
            "error": safe_error,
            "message": safe_message,
            "metadata": metadata or None,
        }
    )
    return match.model_copy(update={"result": sanitized_result})


def _sanitize_evaluation_response(response: EvaluationResponse) -> EvaluationResponse:
    """Return a copy of the evaluation response with safe public error text."""
    return response.model_copy(
        update={
            "matches": (
                [_sanitize_control_match(match) for match in response.matches]
                if response.matches
                else None
            ),
            "errors": (
                [_sanitize_control_match(match) for match in response.errors]
                if response.errors
                else None
            ),
            "non_matches": (
                [_sanitize_control_match(match) for match in response.non_matches]
                if response.non_matches
                else None
            ),
        }
    )


@router.post(
    "",
    response_model=EvaluationResponse,
    summary="Analyze content safety",
    response_description="Safety analysis result",
)
async def evaluate(
    request: EvaluationRequest,
    client: RequireAPIKey,
    db: AsyncSession = Depends(get_async_db),
) -> EvaluationResponse:
    """Analyze content for safety and control violations.

    This endpoint is intentionally evaluation-only. It returns the semantic
    ``EvaluationResponse`` and does not build or ingest observability events
    on the server; SDKs reconstruct and emit those events separately through
    the observability ingestion endpoint.
    """
    del client  # Authentication is still required by dependency injection.

    agent_result = await db.execute(
        select(Agent).where(Agent.name == request.agent_name)
    )
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent '{request.agent_name}' not found",
            resource="Agent",
            resource_id=request.agent_name,
            hint="Register the agent via initAgent before evaluating.",
        )

    api_controls = await list_controls_for_agent(
        request.agent_name,
        db,
        allow_invalid_step_name_regex=True,
    )
    engine_controls = [ControlAdapter(c.id, c.name, c.control) for c in api_controls]

    engine = ControlEngine(engine_controls)
    try:
        raw_response = await engine.process(request)
    except ValueError:
        _logger.exception("Evaluation failed due to invalid configuration or input")
        raise APIValidationError(
            error_code=ErrorCode.EVALUATION_FAILED,
            detail="Evaluation failed due to invalid configuration or input",
            resource="Evaluation",
            hint="Check the evaluation request format and control configurations.",
            errors=[
                ValidationErrorItem(
                    resource="Evaluation",
                    field=None,
                    code="evaluation_error",
                    message=SAFE_ENGINE_VALIDATION_MESSAGE,
                )
            ],
        )

    return _sanitize_evaluation_response(raw_response)
