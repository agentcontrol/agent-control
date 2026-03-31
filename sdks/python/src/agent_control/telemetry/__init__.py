"""Telemetry interfaces for provider-agnostic tracing and event emission."""

from .event_sink import (
    ControlEventSink,
    clear_control_event_sink,
    emit_control_events,
    has_control_event_sink,
    set_control_event_sink,
)
from .otel import (
    configure_otel_event_sink,
    control_event_to_otel_attributes,
    control_event_to_otel_span,
    create_otel_event_sink,
    is_otel_event_emission_configured,
)
from .trace_context import (
    TraceContext,
    TraceContextProvider,
    clear_trace_context_provider,
    get_trace_context_from_provider,
    set_trace_context_provider,
)

__all__ = [
    "ControlEventSink",
    "TraceContext",
    "TraceContextProvider",
    "clear_control_event_sink",
    "clear_trace_context_provider",
    "configure_otel_event_sink",
    "control_event_to_otel_attributes",
    "control_event_to_otel_span",
    "create_otel_event_sink",
    "emit_control_events",
    "get_trace_context_from_provider",
    "has_control_event_sink",
    "is_otel_event_emission_configured",
    "set_control_event_sink",
    "set_trace_context_provider",
]
