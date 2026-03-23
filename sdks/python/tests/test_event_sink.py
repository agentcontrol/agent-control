"""Tests for the telemetry merged control event sink interface."""

from datetime import UTC, datetime

from agent_control.telemetry.event_sink import (
    clear_control_event_sink,
    emit_control_events,
    set_control_event_sink,
)
from agent_control_models import ControlExecutionEvent


def _event() -> ControlExecutionEvent:
    return ControlExecutionEvent(
        control_execution_id="ce-1",
        trace_id="a" * 32,
        span_id="b" * 16,
        agent_name="test-agent",
        control_id=1,
        control_name="pii_check",
        check_stage="pre",
        applies_to="llm_call",
        action="allow",
        matched=False,
        confidence=0.95,
        timestamp=datetime.now(UTC),
        metadata={},
    )


def teardown_function() -> None:
    clear_control_event_sink()


def test_emit_control_events_calls_registered_sink() -> None:
    seen: list[list[ControlExecutionEvent]] = []

    def _sink(events: list[ControlExecutionEvent]) -> None:
        seen.append(events)

    event = _event()
    set_control_event_sink(_sink)

    emit_control_events([event])

    assert seen == [[event]]


def test_emit_control_events_noops_without_sink() -> None:
    emit_control_events([_event()])


def test_emit_control_events_swallows_sink_failures() -> None:
    def _sink(_events: list[ControlExecutionEvent]) -> None:
        raise RuntimeError("boom")

    set_control_event_sink(_sink)

    emit_control_events([_event()])
