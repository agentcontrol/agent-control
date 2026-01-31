"""Evaluation analysis endpoints."""

import time
from datetime import UTC, datetime
from typing import Literal

from agent_control_engine.core import ControlEngine
from agent_control_models import (
    ControlDefinition,
    ControlExecutionEvent,
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


class ControlAdapter:
    """Adapts API Control to Engine ControlWithIdentity protocol."""

    def __init__(self, id: int, name: str, control: ControlDefinition):
        self.id = id
        self.name = name
        self.control = control


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
        select(Agent).where(Agent.agent_uuid == request.agent_uuid)
    )
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent '{request.agent_uuid}' not found",
            resource="Agent",
            resource_id=str(request.agent_uuid),
            hint="Register the agent via initAgent before evaluating.",
        )
    agent_name = agent.name

    # Fetch controls for the agent (already validated as ControlDefinition)
    api_controls = await list_controls_for_agent(
        request.agent_uuid,
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
        response = await engine.process(request)
    except ValueError as e:
        _logger.error(f"Evaluation failed: {e}")
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
                    message=str(e),
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
            response=response,
            request=request,
            trace_id=trace_id,
            span_id=span_id,
            agent_name=agent_name,
            applies_to=applies_to,
            control_lookup=control_lookup,
            total_duration_ms=total_duration_ms,
            ingestor=ingestor,
        )

    return response


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
            events.append(
                ControlExecutionEvent(
                    control_execution_id=match.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_uuid=request.agent_uuid,
                    agent_name=agent_name,
                    control_id=match.control_id,
                    control_name=match.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=match.action,
                    matched=True,
                    confidence=match.result.confidence,
                    timestamp=now,
                    evaluator_name=ctrl.control.evaluator.name if ctrl else None,
                    error_message=match.result.error,
                    metadata=match.result.metadata or {},
                )
            )

    # Process errors (controls that failed during evaluation)
    if response.errors:
        for error in response.errors:
            ctrl = control_lookup.get(error.control_id)
            events.append(
                ControlExecutionEvent(
                    control_execution_id=error.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_uuid=request.agent_uuid,
                    agent_name=agent_name,
                    control_id=error.control_id,
                    control_name=error.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=error.action,
                    matched=False,
                    confidence=error.result.confidence,
                    timestamp=now,
                    evaluator_name=ctrl.control.evaluator.name if ctrl else None,
                    error_message=error.result.error,
                    metadata=error.result.metadata or {},
                )
            )

    # Process non-matches (controls that were evaluated but did not match)
    if response.non_matches:
        for non_match in response.non_matches:
            ctrl = control_lookup.get(non_match.control_id)
            events.append(
                ControlExecutionEvent(
                    control_execution_id=non_match.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_uuid=request.agent_uuid,
                    agent_name=agent_name,
                    control_id=non_match.control_id,
                    control_name=non_match.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=non_match.action,
                    matched=False,
                    confidence=non_match.result.confidence,
                    timestamp=now,
                    evaluator_name=ctrl.control.evaluator.name if ctrl else None,
                    error_message=None,
                    metadata=non_match.result.metadata or {},
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
