"""Evaluation analysis endpoints."""

import time
from datetime import UTC, datetime
from typing import Literal

from agent_control_engine.core import ControlEngine
from agent_control_models import (
    ControlDefinition,
    ControlExecutionEvent,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
)
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import observability_settings
from ..db import get_async_db
from ..errors import APIValidationError, NotFoundError
from ..logging_utils import get_logger
from ..models import Agent
from ..observability.ingest.base import EventIngestor
from ..services.controls import list_controls_for_agent
from .observability import get_event_ingestor

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

_logger = get_logger(__name__)

# OTEL-standard invalid IDs - used when client doesn't provide trace context.
# These are immediately recognizable as "not traced" and can be filtered in queries.
INVALID_TRACE_ID = "0" * 32  # 128-bit, 32 hex chars
INVALID_SPAN_ID = "0" * 16   # 64-bit, 16 hex chars
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


def _observability_metadata(
    control_def: ControlDefinition,
) -> tuple[str | None, str | None, dict[str, object]]:
    """Return representative event fields plus full composite context."""
    identity = control_def.observability_identity()
    return (
        identity.selector_path,
        identity.evaluator_name,
        {
            "primary_evaluator": identity.evaluator_name,
            "primary_selector_path": identity.selector_path,
            "leaf_count": identity.leaf_count,
            "all_evaluators": identity.all_evaluators,
            "all_selector_paths": identity.all_selector_paths,
        },
    )


@router.post(
    "",
    response_model=EvaluationResponse,
    summary="Analyze content safety",
    response_description="Safety analysis result",
)
async def evaluate(
    request: EvaluationRequest,
    req: Request,
    db: AsyncSession = Depends(get_async_db),
    x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
    x_span_id: str | None = Header(default=None, alias="X-Span-Id"),
) -> EvaluationResponse:
    """Analyze content for safety and control violations.

    Runs all controls assigned to the agent via policy through the
    evaluation engine. Controls are evaluated in parallel with
    cancel-on-deny for efficiency.

    Custom evaluators must be deployed as Evaluator classes
    with the engine. Their schemas are registered via initAgent.

    Optionally accepts X-Trace-Id and X-Span-Id headers for
    OpenTelemetry-compatible distributed tracing.
    """
    start_time = time.perf_counter()

    # Use provided trace/span IDs or fall back to OTEL invalid IDs.
    # Invalid IDs make it obvious that trace context wasn't provided by the client.
    if not x_trace_id or not x_span_id:
        _logger.warning(
            "Missing trace context headers (X-Trace-Id, X-Span-Id). "
            "Using invalid IDs - observability data will not be traceable."
        )
    trace_id = x_trace_id or INVALID_TRACE_ID
    span_id = x_span_id or INVALID_SPAN_ID

    # Determine payload type for observability based on step type
    applies_to: Literal["llm_call", "tool_call"] = (
        "tool_call" if request.step.type == "tool" else "llm_call"
    )

    # Fetch agent to get the name
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
    agent_name = agent.name

    # Fetch controls for the agent (already validated as ControlDefinition)
    api_controls = await list_controls_for_agent(
        request.agent_name,
        db,
        allow_invalid_step_name_regex=True,
    )

    # Build control lookup for observability
    control_lookup = {c.id: c for c in api_controls}

    # Adapt controls for the engine
    engine_controls = [ControlAdapter(c.id, c.name, c.control) for c in api_controls]

    # Execute Control Engine (parallel with cancel-on-deny)
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

    # Calculate total execution time
    total_duration_ms = (time.perf_counter() - start_time) * 1000

    # Emit observability events if enabled
    if observability_settings.enabled:
        # Get ingestor from app.state (None if not initialized)
        try:
            ingestor = get_event_ingestor(req)
        except RuntimeError:
            ingestor = None

        await _emit_observability_events(
            response=raw_response,
            request=request,
            trace_id=trace_id,
            span_id=span_id,
            agent_name=agent_name,
            applies_to=applies_to,
            control_lookup=control_lookup,
            total_duration_ms=total_duration_ms,
            ingestor=ingestor,
        )

    return _sanitize_evaluation_response(raw_response)


async def _emit_observability_events(
    response: EvaluationResponse,
    request: EvaluationRequest,
    trace_id: str,
    span_id: str,
    agent_name: str,
    applies_to: Literal["llm_call", "tool_call"],
    control_lookup: dict,
    total_duration_ms: float,
    ingestor: EventIngestor | None,
) -> None:
    """Create and enqueue observability events for all evaluated controls.

    Uses control_execution_id from the engine response to ensure correlation
    between SDK logs and server observability events.
    """
    events: list[ControlExecutionEvent] = []
    now = datetime.now(UTC)

    # Process matches (controls that matched)
    if response.matches:
        for match in response.matches:
            ctrl = control_lookup.get(match.control_id)
            event_metadata = dict(match.result.metadata or {})
            selector_path = None
            evaluator_name = None
            if ctrl:
                selector_path, evaluator_name, identity_metadata = _observability_metadata(
                    ctrl.control
                )
                event_metadata.update(identity_metadata)
            events.append(
                ControlExecutionEvent(
                    control_execution_id=match.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_name=agent_name,
                    control_id=match.control_id,
                    control_name=match.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=match.action,
                    matched=True,
                    confidence=match.result.confidence,
                    timestamp=now,
                    evaluator_name=evaluator_name,
                    selector_path=selector_path,
                    error_message=match.result.error,
                    metadata=event_metadata,
                )
            )

    # Process errors (controls that failed during evaluation)
    if response.errors:
        for error in response.errors:
            ctrl = control_lookup.get(error.control_id)
            event_metadata = dict(error.result.metadata or {})
            selector_path = None
            evaluator_name = None
            if ctrl:
                selector_path, evaluator_name, identity_metadata = _observability_metadata(
                    ctrl.control
                )
                event_metadata.update(identity_metadata)
            events.append(
                ControlExecutionEvent(
                    control_execution_id=error.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_name=agent_name,
                    control_id=error.control_id,
                    control_name=error.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=error.action,
                    matched=False,
                    confidence=error.result.confidence,
                    timestamp=now,
                    evaluator_name=evaluator_name,
                    selector_path=selector_path,
                    error_message=error.result.error,
                    metadata=event_metadata,
                )
            )

    # Process non-matches (controls that were evaluated but did not match)
    if response.non_matches:
        for non_match in response.non_matches:
            ctrl = control_lookup.get(non_match.control_id)
            event_metadata = dict(non_match.result.metadata or {})
            selector_path = None
            evaluator_name = None
            if ctrl:
                selector_path, evaluator_name, identity_metadata = _observability_metadata(
                    ctrl.control
                )
                event_metadata.update(identity_metadata)
            events.append(
                ControlExecutionEvent(
                    control_execution_id=non_match.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_name=agent_name,
                    control_id=non_match.control_id,
                    control_name=non_match.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=non_match.action,
                    matched=False,
                    confidence=non_match.result.confidence,
                    timestamp=now,
                    evaluator_name=evaluator_name,
                    selector_path=selector_path,
                    error_message=None,
                    metadata=event_metadata,
                )
            )

    # Ingest events
    if events and ingestor:
        result = await ingestor.ingest(events)
        if result.dropped > 0:
            _logger.warning(
                f"Dropped {result.dropped} observability events, "
                f"processed {result.processed}"
            )
