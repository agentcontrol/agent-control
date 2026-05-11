"""Tests for the built-in OpenTelemetry control-event sink."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import cast
from unittest.mock import patch

from agent_control_models import ControlExecutionEvent

from agent_control import add_event, init_observability, sync_shutdown_observability
from agent_control.observability import is_observability_enabled
from agent_control.otel_sink import (
    OTEL_CONTROL_EVENT_SINK_NAME,
    OTELControlEventSink,
    OTELSDKModules,
    control_event_to_otel_span,
    create_otel_control_event_sink,
)
from agent_control.settings import configure_settings, get_settings


def _make_event(**overrides: object) -> ControlExecutionEvent:
    event = ControlExecutionEvent(
        control_execution_id="ce-123",
        trace_id="a" * 32,
        span_id="b" * 16,
        agent_name="test-agent",
        control_id=7,
        control_name="detect-pii",
        check_stage="pre",
        applies_to="llm_call",
        action="observe",
        matched=True,
        confidence=0.85,
        timestamp=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
        execution_duration_ms=12.5,
        evaluator_name="regex",
        selector_path="input",
        error_message=None,
        metadata={"labels": ["security", "pii"], "threshold": 3, "nested": {"k": "v"}},
    )
    return event.model_copy(update=overrides)


class FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.end_time: int | None = None
        self.exceptions: list[str] = []
        self.status: FakeStatus | None = None

    def set_attributes(self, attributes: dict[str, object]) -> None:
        self.attributes = dict(attributes)

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(str(exc))

    def set_status(self, status: FakeStatus) -> None:
        self.status = status

    def end(self, end_time: int) -> None:
        self.end_time = end_time


class FakeTracer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.spans: list[FakeSpan] = []

    def start_span(
        self,
        name: str,
        *,
        context: object = None,
        kind: object = None,
        start_time: int | None = None,
    ) -> FakeSpan:
        self.calls.append(
            {
                "name": name,
                "context": context,
                "kind": kind,
                "start_time": start_time,
            }
        )
        span = FakeSpan()
        self.spans.append(span)
        return span


class FakeTracerProvider:
    def __init__(self, *, resource: object) -> None:
        self.resource = resource
        self.processors: list[object] = []
        self.tracer = FakeTracer()
        self.force_flush_calls = 0
        self.shutdown_calls = 0
        self.tracer_scope_name: str | None = None

    def add_span_processor(self, processor: object) -> None:
        self.processors.append(processor)

    def get_tracer(self, name: str) -> FakeTracer:
        self.tracer_scope_name = name
        return self.tracer

    def force_flush(self) -> None:
        self.force_flush_calls += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class FakeResource:
    @staticmethod
    def create(attributes: dict[str, object]) -> dict[str, object]:
        return {"attributes": attributes}


class FakeBatchSpanProcessor:
    def __init__(self, exporter: object) -> None:
        self.exporter = exporter


class FakeOTLPSpanExporter:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class FakeSpanContext:
    def __init__(
        self,
        *,
        trace_id: int,
        span_id: int,
        is_remote: bool,
        trace_flags: object,
        trace_state: object,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.is_remote = is_remote
        self.trace_flags = trace_flags
        self.trace_state = trace_state


class FakeNonRecordingSpan:
    def __init__(self, span_context: FakeSpanContext) -> None:
        self.span_context = span_context


class FakeTraceFlags(int):
    SAMPLED = 1


class FakeTraceState:
    pass


class FakeStatusCode:
    ERROR = "error"


class FakeStatus:
    def __init__(self, status_code: object, description: str | None = None) -> None:
        self.status_code = status_code
        self.description = description


class FakeSpanKind:
    INTERNAL = "internal"


def _fake_set_span_in_context(span: FakeNonRecordingSpan) -> dict[str, object]:
    return {"parent": span}


def _fake_otel_sdk_modules() -> OTELSDKModules:
    return OTELSDKModules(
        tracer_provider_cls=FakeTracerProvider,
        resource_cls=FakeResource,
        batch_span_processor_cls=FakeBatchSpanProcessor,
        otlp_span_exporter_cls=FakeOTLPSpanExporter,
        span_context_cls=FakeSpanContext,
        non_recording_span_cls=FakeNonRecordingSpan,
        trace_flags_cls=FakeTraceFlags,
        trace_state_cls=FakeTraceState,
        status_cls=FakeStatus,
        status_code_cls=FakeStatusCode,
        span_kind=FakeSpanKind,
        set_span_in_context=_fake_set_span_in_context,
    )


def setup_function() -> None:
    original_settings = get_settings().model_dump()
    setup_function.original_settings = original_settings  # type: ignore[attr-defined]
    configure_settings(
        observability_enabled=True,
        observability_sink_name="default",
        observability_sink_config={},
        otel_enabled=False,
        otel_endpoint=None,
        otel_headers={},
        otel_service_name="agent-control-sdk",
    )
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    os.environ.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)


def teardown_function() -> None:
    sync_shutdown_observability()
    configure_settings(**setup_function.original_settings)  # type: ignore[attr-defined]


def test_control_event_to_otel_span_maps_event_fields() -> None:
    event = _make_event(error_message="blocked")

    span = control_event_to_otel_span(event)

    assert span.trace_id == event.trace_id
    assert span.parent_span_id == event.span_id
    assert span.name == "agent_control.control_execution"
    assert span.attributes["agent_control.control_name"] == "detect-pii"
    assert span.attributes["agent_control.matched"] is True
    assert span.attributes["agent_control.metadata.labels"] == ["security", "pii"]
    assert span.attributes["agent_control.metadata.nested"] == '{"k": "v"}'
    assert span.error_message == "blocked"
    assert span.end_time_unix_nano >= span.start_time_unix_nano


def test_create_otel_control_event_sink_is_inert_when_disabled() -> None:
    configure_settings(otel_enabled=False)

    sink = create_otel_control_event_sink({})
    result = sink.write_events([_make_event()])

    assert sink.is_active() is False
    assert result.accepted == 1
    assert result.dropped == 0


def test_create_otel_control_event_sink_without_exporter_stays_inert() -> None:
    configure_settings(otel_enabled=True, otel_endpoint=None)

    with patch(
        "agent_control.otel_sink._load_otel_sdk_modules",
        return_value=_fake_otel_sdk_modules(),
    ):
        sink = create_otel_control_event_sink({})

    assert sink.is_active() is False


def test_create_otel_control_event_sink_uses_exporter_config_and_emits_spans() -> None:
    configure_settings(
        otel_enabled=True,
        otel_endpoint="http://collector:4318/v1/traces",
        otel_headers={"x-api-key": "secret"},
        otel_service_name="agent-control-tests",
    )

    with patch(
        "agent_control.otel_sink._load_otel_sdk_modules",
        return_value=_fake_otel_sdk_modules(),
    ):
        sink = create_otel_control_event_sink({})

    assert isinstance(sink, OTELControlEventSink)
    tracer_provider = sink._tracer_provider
    assert isinstance(tracer_provider, FakeTracerProvider)
    assert tracer_provider.resource == {"attributes": {"service.name": "agent-control-tests"}}
    assert len(tracer_provider.processors) == 1

    processor = tracer_provider.processors[0]
    assert isinstance(processor, FakeBatchSpanProcessor)
    assert isinstance(processor.exporter, FakeOTLPSpanExporter)
    assert processor.exporter.kwargs == {
        "endpoint": "http://collector:4318/v1/traces",
        "headers": {"x-api-key": "secret"},
    }

    event = _make_event(error_message="rule failed")
    result = sink.write_events([event])

    assert result.accepted == 1
    assert result.dropped == 0
    assert len(tracer_provider.tracer.calls) == 1
    first_call = tracer_provider.tracer.calls[0]
    assert first_call["name"] == "agent_control.control_execution"
    assert first_call["kind"] == FakeSpanKind.INTERNAL
    context = first_call["context"]
    assert isinstance(context, dict)
    parent_span = context["parent"]
    assert isinstance(parent_span, FakeNonRecordingSpan)
    assert parent_span.span_context.trace_id == int(event.trace_id, 16)
    assert parent_span.span_context.span_id == int(event.span_id, 16)
    span = tracer_provider.tracer.spans[0]
    assert span.attributes["agent_control.agent_name"] == event.agent_name
    assert span.attributes["agent_control.error_message"] == "rule failed"
    assert span.exceptions == ["rule failed"]
    assert span.status is not None
    assert span.status.status_code == FakeStatusCode.ERROR
    assert span.status.description == "rule failed"

    sink.flush()
    sink.close()
    assert tracer_provider.force_flush_calls == 1
    assert tracer_provider.shutdown_calls == 1


def test_observability_uses_builtin_otel_sink_when_selected() -> None:
    configure_settings(
        observability_sink_name=OTEL_CONTROL_EVENT_SINK_NAME,
        otel_enabled=True,
        otel_endpoint="http://collector:4318/v1/traces",
    )

    with patch(
        "agent_control.otel_sink._load_otel_sdk_modules",
        return_value=_fake_otel_sdk_modules(),
    ):
        batcher = init_observability(enabled=True)
        result = add_event(_make_event())

    assert batcher is None
    assert result is True


def test_init_disabled_persists_override_for_builtin_otel_sink() -> None:
    configure_settings(
        observability_sink_name=OTEL_CONTROL_EVENT_SINK_NAME,
        otel_enabled=True,
        otel_endpoint="http://collector:4318/v1/traces",
    )

    with patch(
        "agent_control.otel_sink._load_otel_sdk_modules",
        return_value=_fake_otel_sdk_modules(),
    ) as load_otel_sdk_modules:
        batcher = init_observability(enabled=False)

        assert batcher is None
        assert get_settings().observability_enabled is False
        assert is_observability_enabled() is False
        assert add_event(_make_event()) is False

    load_otel_sdk_modules.assert_not_called()


def test_observability_does_not_activate_inert_otel_sink() -> None:
    configure_settings(
        observability_sink_name=OTEL_CONTROL_EVENT_SINK_NAME,
        otel_enabled=True,
        otel_endpoint=None,
    )

    with patch(
        "agent_control.otel_sink._load_otel_sdk_modules",
        return_value=_fake_otel_sdk_modules(),
    ):
        batcher = init_observability(enabled=True)
        assert batcher is None
        assert is_observability_enabled() is False

        result = add_event(_make_event())

    assert result is False


def test_observability_rebuilds_otel_sink_when_effective_settings_change() -> None:
    import agent_control.observability as obs

    configure_settings(
        observability_sink_name=OTEL_CONTROL_EVENT_SINK_NAME,
        otel_enabled=True,
        otel_endpoint="http://collector:4318/v1/traces",
    )

    with patch(
        "agent_control.otel_sink._load_otel_sdk_modules",
        return_value=_fake_otel_sdk_modules(),
    ):
        assert add_event(_make_event()) is True
        first_sink = cast(OTELControlEventSink, obs._configured_named_event_sink)
        first_provider = first_sink._tracer_provider

        configure_settings(otel_endpoint="http://collector-2:4318/v1/traces")

        assert add_event(_make_event(control_execution_id="ce-456")) is True
        second_sink = cast(OTELControlEventSink, obs._configured_named_event_sink)

    assert second_sink is not None
    assert first_sink is not second_sink
    assert first_provider.shutdown_calls == 1
    assert obs._configured_named_event_sink_selection is not None
    assert obs._configured_named_event_sink_selection.config["endpoint"] == (
        "http://collector-2:4318/v1/traces"
    )
