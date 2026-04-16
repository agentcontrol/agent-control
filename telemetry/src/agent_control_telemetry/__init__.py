"""Shared telemetry contracts for Agent Control."""

from .sink_selection import (
    DEFAULT_CONTROL_EVENT_SINK_NAME,
    REGISTERED_CONTROL_EVENT_SINK_NAME,
    ControlEventSinkFactory,
    ControlEventSinkFactoryRegistry,
    ControlEventSinkSelection,
    SinkSelectionError,
)
from .sinks import (
    AsyncControlEventSink,
    BaseAsyncControlEventSink,
    BaseControlEventSink,
    ControlEventSink,
    SinkResult,
)
from .trace_context import (
    TraceContext,
    TraceContextProvider,
    clear_trace_context_provider,
    get_trace_context_from_provider,
    set_trace_context_provider,
)

__all__ = [
    "AsyncControlEventSink",
    "BaseAsyncControlEventSink",
    "BaseControlEventSink",
    "ControlEventSink",
    "SinkResult",
    "DEFAULT_CONTROL_EVENT_SINK_NAME",
    "REGISTERED_CONTROL_EVENT_SINK_NAME",
    "ControlEventSinkFactory",
    "ControlEventSinkFactoryRegistry",
    "ControlEventSinkSelection",
    "SinkSelectionError",
    "TraceContext",
    "TraceContextProvider",
    "clear_trace_context_provider",
    "get_trace_context_from_provider",
    "set_trace_context_provider",
]
