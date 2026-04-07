"""Derived control-execution event reconstruction for SDK evaluation flows."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from agent_control_models import (
    ControlDefinition,
    ControlDefinitionRuntime,
    ControlExecutionEvent,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
)

from .observability import get_logger, is_observability_enabled, write_events

_logger = get_logger(__name__)

# All-zero values are invalid trace/span IDs per OpenTelemetry and make it
# obvious that the event could not be correlated to an external trace.
_FALLBACK_TRACE_ID = "0" * 32
_FALLBACK_SPAN_ID = "0" * 16
_trace_warning_logged = False


def observability_metadata(
    control_def: ControlDefinition | ControlDefinitionRuntime,
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


def map_applies_to(step_type: str) -> Literal["llm_call", "tool_call"]:
    """Map Agent Control step types to observability applies_to values."""
    return "tool_call" if step_type == "tool" else "llm_call"


def _resolve_event_trace_context(
    trace_id: str | None,
    span_id: str | None,
) -> tuple[str, str]:
    """Return event IDs, applying fallback IDs and a one-time warning if needed."""
    global _trace_warning_logged  # noqa: PLW0603

    if trace_id and span_id:
        return trace_id, span_id

    if not _trace_warning_logged:
        _logger.warning(
            "Emitting control events without trace context; events will use fallback "
            "IDs and cannot be correlated with traces. Pass trace_id/span_id for "
            "full observability."
        )
        _trace_warning_logged = True

    return trace_id or _FALLBACK_TRACE_ID, span_id or _FALLBACK_SPAN_ID


def _build_events_for_matches(
    matches: list[ControlMatch] | None,
    *,
    matched: bool,
    include_error_message: bool,
    request: EvaluationRequest,
    control_lookup: Mapping[int, ControlDefinition | ControlDefinitionRuntime],
    trace_id: str,
    span_id: str,
    agent_name: str,
    now: datetime,
) -> list[ControlExecutionEvent]:
    if not matches:
        return []

    applies_to = map_applies_to(request.step.type)
    events: list[ControlExecutionEvent] = []

    for match in matches:
        control_def = control_lookup.get(match.control_id)
        event_metadata = dict(match.result.metadata or {})
        selector_path = None
        evaluator_name = None

        if control_def is not None:
            selector_path, evaluator_name, identity_metadata = observability_metadata(control_def)
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
                matched=matched,
                confidence=match.result.confidence,
                timestamp=now,
                evaluator_name=evaluator_name,
                selector_path=selector_path,
                error_message=match.result.error if include_error_message else None,
                metadata=event_metadata,
            )
        )

    return events


def build_control_execution_events(
    response: EvaluationResponse,
    request: EvaluationRequest,
    control_lookup: Mapping[int, ControlDefinition | ControlDefinitionRuntime],
    trace_id: str | None,
    span_id: str | None,
    agent_name: str | None,
) -> list[ControlExecutionEvent]:
    """Reconstruct control execution events from an evaluation response.

    This is the shared reconstruction step used by both supported event
    creation styles:
    - the default SDK observability path, where reconstructed local events are
      queued into the existing SDK batcher
    - the merged-event path, where local and server events are reconstructed in
      the SDK and queued together through the existing SDK batcher

    Args:
        response: Evaluation response containing matches, errors, and
            non-matches.
        request: Original evaluation request used to derive stage and
            ``applies_to``.
        control_lookup: Parsed controls keyed by control ID.
        trace_id: Optional trace ID for correlation.
        span_id: Optional span ID for correlation.
        agent_name: Optional override for the agent name stamped on events.

    Returns:
        A list of reconstructed ``ControlExecutionEvent`` objects.
    """
    resolved_trace_id, resolved_span_id = _resolve_event_trace_context(trace_id, span_id)
    resolved_agent_name = agent_name or request.agent_name
    now = datetime.now(UTC)

    events: list[ControlExecutionEvent] = []
    events.extend(
        _build_events_for_matches(
            response.matches,
            matched=True,
            include_error_message=True,
            request=request,
            control_lookup=control_lookup,
            trace_id=resolved_trace_id,
            span_id=resolved_span_id,
            agent_name=resolved_agent_name,
            now=now,
        )
    )
    events.extend(
        _build_events_for_matches(
            response.errors,
            matched=False,
            include_error_message=True,
            request=request,
            control_lookup=control_lookup,
            trace_id=resolved_trace_id,
            span_id=resolved_span_id,
            agent_name=resolved_agent_name,
            now=now,
        )
    )
    events.extend(
        _build_events_for_matches(
            response.non_matches,
            matched=False,
            include_error_message=False,
            request=request,
            control_lookup=control_lookup,
            trace_id=resolved_trace_id,
            span_id=resolved_span_id,
            agent_name=resolved_agent_name,
            now=now,
        )
    )
    return events


def enqueue_observability_events(events: list[ControlExecutionEvent]) -> None:
    """Enqueue reconstructed events through the existing SDK observability path.

    This preserves the built-in SDK behavior of forwarding events through the
    existing observability batcher.

    Args:
        events: Reconstructed control execution events to enqueue.

    Returns:
        None.
    """
    if not is_observability_enabled():
        return

    write_events(events)
