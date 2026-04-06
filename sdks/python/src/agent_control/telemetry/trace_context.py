"""Provider-agnostic trace context interface for external tracing systems."""

from collections.abc import Callable
from typing import TypedDict


class TraceContext(TypedDict):
    """Resolved trace context for a control evaluation."""

    trace_id: str
    span_id: str


TraceContextProvider = Callable[[], TraceContext | None]

_trace_context_provider: TraceContextProvider | None = None


def set_trace_context_provider(provider: TraceContextProvider | None) -> None:
    """Register a provider that returns the current trace context."""
    global _trace_context_provider
    _trace_context_provider = provider


def get_trace_context_from_provider() -> TraceContext | None:
    """Return trace context from the registered provider, if any."""
    if _trace_context_provider is None:
        return None

    try:
        trace_context = _trace_context_provider()
    except Exception:
        # Provider failures should not break control evaluation.
        return None

    if trace_context is None:
        return None

    trace_id = trace_context.get("trace_id")
    span_id = trace_context.get("span_id")
    if not isinstance(trace_id, str) or not isinstance(span_id, str):
        return None
    if not trace_id or not span_id:
        return None

    return {
        "trace_id": trace_id,
        "span_id": span_id,
    }


def clear_trace_context_provider() -> None:
    """Clear the registered trace context provider."""
    global _trace_context_provider
    _trace_context_provider = None
