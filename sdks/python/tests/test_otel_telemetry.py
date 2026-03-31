"""Tests for OTEL emission support for merged control execution events."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from agent_control.telemetry.event_sink import clear_control_event_sink
from agent_control.telemetry.otel import (
    configure_otel_event_sink,
    control_event_to_otel_attributes,
    control_event_to_otel_span,
    create_otel_event_sink,
    is_otel_event_emission_configured,
)
from agent_control.settings import SDKSettings
from agent_control_models import ControlExecutionEvent


class _FakeSpan:
    def __init__(self) -> None:
        self.ended_with: int | None = None

    def end(self, end_time: int | None = None) -> None:
        self.ended_with = end_time


class _FakeTracer:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.spans: list[_FakeSpan] = []

    def start_span(self, **kwargs):
        self.calls.append(kwargs)
        span = _FakeSpan()
        self.spans.append(span)
        return span


def _make_event(**overrides) -> ControlExecutionEvent:
    base = {
        "control_execution_id": "ce-123",
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
        "agent_name": "agent-000000000001",
        "control_id": 1,
        "control_name": "policy-check",
        "check_stage": "pre",
        "applies_to": "llm_call",
        "action": "deny",
        "matched": True,
        "confidence": 0.91,
        "timestamp": datetime(2026, 3, 31, 12, 0, tzinfo=UTC),
        "execution_duration_ms": 7.5,
        "evaluator_name": "regex",
        "selector_path": "input",
        "error_message": None,
        "metadata": {"leaf_count": 2, "condition_trace": {"kind": "and"}},
    }
    base.update(overrides)
    return ControlExecutionEvent(**base)


def teardown_function() -> None:
    clear_control_event_sink()


def test_is_otel_event_emission_configured_detects_settings() -> None:
    assert is_otel_event_emission_configured(SDKSettings(otel_enabled=True)) is True
    assert is_otel_event_emission_configured(SDKSettings(otel_endpoint="http://collector")) is True
    assert is_otel_event_emission_configured(SDKSettings()) is False


def test_control_event_to_otel_attributes_maps_expected_fields() -> None:
    event = _make_event(error_message="blocked")

    attrs = control_event_to_otel_attributes(event)

    assert attrs["gen_ai.system"] == "agent-control"
    assert attrs["agent_control.event_type"] == "control_execution"
    assert attrs["agent_control.control_execution_id"] == "ce-123"
    assert attrs["agent_control.agent_name"] == "agent-000000000001"
    assert attrs["agent_control.control_id"] == 1
    assert attrs["agent_control.action"] == "deny"
    assert attrs["agent_control.matched"] is True
    assert attrs["agent_control.confidence"] == 0.91
    assert attrs["agent_control.evaluator_name"] == "regex"
    assert attrs["agent_control.selector_path"] == "input"
    assert attrs["agent_control.error_message"] == "blocked"
    assert attrs["agent_control.metadata.leaf_count"] == 2
    assert attrs["agent_control.metadata.condition_trace"] == '{"kind": "and"}'


def test_control_event_to_otel_span_uses_parent_context_and_timing() -> None:
    tracer = _FakeTracer()
    event = _make_event()

    with patch("agent_control.telemetry.otel._build_parent_context", return_value="ctx"):
        control_event_to_otel_span(event, tracer)

    assert len(tracer.calls) == 1
    call = tracer.calls[0]
    assert call["name"] == "control:policy-check"
    assert call["context"] == "ctx"
    assert call["attributes"]["agent_control.control_name"] == "policy-check"
    assert call["start_time"] == int(event.timestamp.timestamp() * 1_000_000_000)
    assert tracer.spans[0].ended_with == call["start_time"] + 7_500_000


def test_create_otel_event_sink_uses_configured_tracer() -> None:
    tracer = _FakeTracer()
    event = _make_event()

    with patch("agent_control.telemetry.otel._ensure_otel_tracer", return_value=tracer):
        sink = create_otel_event_sink(SDKSettings(otel_enabled=True))

    assert sink is not None
    with patch("agent_control.telemetry.otel._build_parent_context", return_value=None):
        sink([event])

    assert tracer.calls[0]["attributes"]["agent_control.control_execution_id"] == "ce-123"


def test_configure_otel_event_sink_registers_when_no_sink_exists() -> None:
    fake_sink = MagicMock()

    with patch("agent_control.telemetry.otel.has_control_event_sink", return_value=False), \
         patch("agent_control.telemetry.otel.create_otel_event_sink", return_value=fake_sink), \
         patch("agent_control.telemetry.otel.set_control_event_sink") as mock_set:
        configured = configure_otel_event_sink(SDKSettings(otel_enabled=True))

    assert configured is True
    mock_set.assert_called_once_with(fake_sink)


def test_configure_otel_event_sink_does_not_override_existing_sink() -> None:
    with patch("agent_control.telemetry.otel.has_control_event_sink", return_value=True), \
         patch("agent_control.telemetry.otel.create_otel_event_sink") as mock_create:
        configured = configure_otel_event_sink(SDKSettings(otel_enabled=True))

    assert configured is False
    mock_create.assert_not_called()
