"""Telemetry interfaces for provider-agnostic tracing and event emission."""

from .event_sink import (
    ControlEventSink,
    clear_control_event_sink,
    emit_control_events,
    set_control_event_sink,
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
    "emit_control_events",
    "get_trace_context_from_provider",
    "set_control_event_sink",
    "set_trace_context_provider",
]
