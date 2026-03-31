"""OTEL emission helpers for merged control execution events."""

from __future__ import annotations

import importlib
import json
from datetime import UTC
from typing import Any

from agent_control_models import ControlExecutionEvent

from ..settings import SDKSettings, get_settings
from ..tracing import validate_span_id, validate_trace_id
from .event_sink import ControlEventSink, has_control_event_sink, set_control_event_sink


def _import_optional_module(module_name: str) -> Any | None:
    """Import a module if available.

    Args:
        module_name: Fully-qualified module name.

    Returns:
        Imported module object when available, otherwise ``None``.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError:  # pragma: no cover - exercised in environments without OTEL installed
        return None


def _import_optional_attr(module_name: str, attr_name: str) -> Any | None:
    """Import an attribute from an optional module.

    Args:
        module_name: Fully-qualified module name.
        attr_name: Attribute to load from that module.

    Returns:
        The imported attribute when available, otherwise ``None``.
    """
    module = _import_optional_module(module_name)
    if module is None:
        return None
    return getattr(module, attr_name, None)


trace: Any | None = _import_optional_module("opentelemetry.trace")
OTLPSpanExporter: Any | None = _import_optional_attr(
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "OTLPSpanExporter",
)
Resource: Any | None = _import_optional_attr("opentelemetry.sdk.resources", "Resource")
TracerProvider: Any | None = _import_optional_attr(
    "opentelemetry.sdk.trace",
    "TracerProvider",
)
BatchSpanProcessor: Any | None = _import_optional_attr(
    "opentelemetry.sdk.trace.export",
    "BatchSpanProcessor",
)
NonRecordingSpan: Any | None = _import_optional_attr(
    "opentelemetry.trace",
    "NonRecordingSpan",
)
SpanContext: Any | None = _import_optional_attr("opentelemetry.trace", "SpanContext")
TraceFlags: Any | None = _import_optional_attr("opentelemetry.trace", "TraceFlags")
TraceState: Any | None = _import_optional_attr("opentelemetry.trace", "TraceState")
set_span_in_context: Any | None = _import_optional_attr(
    "opentelemetry.trace",
    "set_span_in_context",
)

_OTEL_SYSTEM = "agent-control"
_OTEL_EVENT_TYPE = "control_execution"
_TRACER_NAME = "agent_control.telemetry.otel"
_TRACER_VERSION = "1.0"
_otel_sink_configured = False


def is_otel_event_emission_configured(
    sdk_settings: SDKSettings | None = None,
) -> bool:
    """Return whether OTEL emission is configured.

    Args:
        sdk_settings: Optional explicit SDK settings instance.

    Returns:
        ``True`` when OTEL emission has been enabled or an OTLP endpoint has
        been configured.
    """
    effective_settings = sdk_settings or get_settings()
    return effective_settings.otel_enabled or bool(effective_settings.otel_endpoint)


def control_event_to_otel_attributes(
    event: ControlExecutionEvent,
) -> dict[str, str | bool | float | int]:
    """Convert a control execution event into OTEL span attributes.

    Args:
        event: Control execution event to translate.

    Returns:
        A dictionary of OTEL span attributes representing the control event.
    """
    attributes: dict[str, str | bool | float | int] = {
        "gen_ai.system": _OTEL_SYSTEM,
        "agent_control.event_type": _OTEL_EVENT_TYPE,
        "agent_control.control_execution_id": event.control_execution_id,
        "agent_control.agent_name": event.agent_name,
        "agent_control.control_id": event.control_id,
        "agent_control.control_name": event.control_name,
        "agent_control.check_stage": event.check_stage,
        "agent_control.applies_to": event.applies_to,
        "agent_control.action": event.action,
        "agent_control.matched": event.matched,
        "agent_control.confidence": event.confidence,
    }

    if event.execution_duration_ms is not None:
        attributes["agent_control.execution_duration_ms"] = event.execution_duration_ms
    if event.evaluator_name is not None:
        attributes["agent_control.evaluator_name"] = event.evaluator_name
    if event.selector_path is not None:
        attributes["agent_control.selector_path"] = event.selector_path
    if event.error_message is not None:
        attributes["agent_control.error_message"] = event.error_message

    for key, value in event.metadata.items():
        attr_key = f"agent_control.metadata.{key}"
        if isinstance(value, (bool, int, float, str)):
            attributes[attr_key] = value
        else:
            attributes[attr_key] = json.dumps(value, sort_keys=True, default=str)

    return attributes


def _build_parent_context(trace_id: str | None, span_id: str | None) -> Any | None:
    """Build an OTEL parent context from event IDs when they are valid."""
    if not trace_id or not span_id:
        return None
    if not validate_trace_id(trace_id) or not validate_span_id(span_id):
        return None
    if (
        NonRecordingSpan is None
        or SpanContext is None
        or TraceFlags is None
        or TraceState is None
        or set_span_in_context is None
    ):
        return None

    parent_span = NonRecordingSpan(
        SpanContext(
            trace_id=int(trace_id, 16),
            span_id=int(span_id, 16),
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
    )
    return set_span_in_context(parent_span)


def control_event_to_otel_span(
    event: ControlExecutionEvent,
    tracer: Any,
) -> None:
    """Emit one control execution event as an OTEL span.

    Args:
        event: Control execution event to emit.
        tracer: OTEL tracer used to create the span.

    Returns:
        None.
    """
    parent_context = _build_parent_context(event.trace_id, event.span_id)
    start_time = int(event.timestamp.astimezone(UTC).timestamp() * 1_000_000_000)
    end_time = start_time
    if event.execution_duration_ms is not None:
        end_time += int(event.execution_duration_ms * 1_000_000)

    span = tracer.start_span(
        name=f"control:{event.control_name}",
        context=parent_context,
        start_time=start_time,
        attributes=control_event_to_otel_attributes(event),
    )
    span.end(end_time=end_time)


def _ensure_otel_tracer(
    sdk_settings: SDKSettings,
) -> Any | None:
    """Return a configured OTEL tracer for control execution spans."""
    if trace is None:
        return None

    global _otel_sink_configured

    if sdk_settings.otel_endpoint and not _otel_sink_configured:
        if (
            OTLPSpanExporter is None
            or Resource is None
            or TracerProvider is None
            or BatchSpanProcessor is None
        ):
            return None

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider(
                resource=Resource.create({"service.name": sdk_settings.otel_service_name})
            )
            trace.set_tracer_provider(provider)

        exporter = OTLPSpanExporter(
            endpoint=sdk_settings.otel_endpoint,
            headers=sdk_settings.otel_headers or None,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _otel_sink_configured = True

    return trace.get_tracer(_TRACER_NAME, _TRACER_VERSION)


def create_otel_event_sink(
    sdk_settings: SDKSettings | None = None,
) -> ControlEventSink | None:
    """Create a merged-event sink that emits OTEL spans.

    Args:
        sdk_settings: Optional explicit SDK settings instance.

    Returns:
        A control event sink when OTEL support is available, otherwise ``None``.
    """
    effective_settings = sdk_settings or get_settings()
    tracer = _ensure_otel_tracer(effective_settings)
    if tracer is None:
        return None

    def sink(events: list[ControlExecutionEvent]) -> None:
        for event in events:
            control_event_to_otel_span(event, tracer)

    return sink


def configure_otel_event_sink(
    sdk_settings: SDKSettings | None = None,
) -> bool:
    """Register the OTEL merged-event sink when OTEL settings are present.

    Args:
        sdk_settings: Optional explicit SDK settings instance.

    Returns:
        ``True`` when the OTEL sink was registered, otherwise ``False``.
    """
    effective_settings = sdk_settings or get_settings()
    if not is_otel_event_emission_configured(effective_settings):
        return False
    if has_control_event_sink():
        return False

    sink = create_otel_event_sink(effective_settings)
    if sink is None:
        return False

    set_control_event_sink(sink)
    return True
