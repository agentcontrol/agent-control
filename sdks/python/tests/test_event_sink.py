"""Tests for configurable control event sinks."""

from unittest.mock import MagicMock, patch

from agent_control.telemetry.event_sink import (
    clear_control_event_sink,
    emit_control_events,
    has_control_event_sink,
    set_control_event_sink,
)
from agent_control_models import ControlExecutionEvent


def _make_event() -> ControlExecutionEvent:
    return ControlExecutionEvent(
        trace_id="a" * 32,
        span_id="b" * 16,
        agent_name="agent-000000000001",
        control_id=1,
        control_name="ctrl-1",
        check_stage="pre",
        applies_to="llm_call",
        action="allow",
        matched=True,
        confidence=1.0,
    )


def teardown_function() -> None:
    clear_control_event_sink()


def test_emit_control_events_uses_default_enqueue_path_without_custom_sink() -> None:
    events = [_make_event()]

    with patch("agent_control.telemetry.event_sink.enqueue_observability_events") as mock_enqueue:
        emit_control_events(events)

    mock_enqueue.assert_called_once_with(events)


def test_emit_control_events_uses_registered_custom_sink() -> None:
    events = [_make_event()]
    sink = MagicMock()
    set_control_event_sink(sink)

    with patch("agent_control.telemetry.event_sink.enqueue_observability_events") as mock_enqueue:
        emit_control_events(events)

    sink.assert_called_once_with(events)
    mock_enqueue.assert_not_called()


def test_emit_control_events_swallows_custom_sink_errors() -> None:
    events = [_make_event()]
    sink = MagicMock(side_effect=RuntimeError("boom"))
    set_control_event_sink(sink)

    with patch("agent_control.telemetry.event_sink._logger") as mock_logger, \
         patch("agent_control.telemetry.event_sink.enqueue_observability_events") as mock_enqueue:
        emit_control_events(events)

    sink.assert_called_once_with(events)
    mock_logger.exception.assert_called_once()
    mock_enqueue.assert_not_called()


def test_emit_control_events_noops_for_empty_event_batch() -> None:
    sink = MagicMock()
    set_control_event_sink(sink)

    with patch("agent_control.telemetry.event_sink.enqueue_observability_events") as mock_enqueue:
        emit_control_events([])

    sink.assert_not_called()
    mock_enqueue.assert_not_called()


def test_has_control_event_sink_tracks_registration() -> None:
    assert has_control_event_sink() is False

    set_control_event_sink(lambda events: None)
    assert has_control_event_sink() is True

    clear_control_event_sink()
    assert has_control_event_sink() is False
