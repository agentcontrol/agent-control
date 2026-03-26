"""Provider-agnostic sink for merged control execution events."""

from collections.abc import Callable

from agent_control_models import ControlExecutionEvent

ControlEventSink = Callable[[list[ControlExecutionEvent]], None]

_control_event_sink: ControlEventSink | None = None


def set_control_event_sink(sink: ControlEventSink | None) -> None:
    """Register a sink for merged control execution events."""
    global _control_event_sink
    _control_event_sink = sink


def emit_control_events(events: list[ControlExecutionEvent]) -> None:
    """Emit merged control execution events to the registered sink."""
    if not events or _control_event_sink is None:
        return

    try:
        _control_event_sink(events)
    except Exception:
        # Sink failures should not break control evaluation.
        pass


def has_control_event_sink() -> bool:
    """Return whether a merged control event sink is currently registered."""
    return _control_event_sink is not None


def clear_control_event_sink() -> None:
    """Clear the registered control event sink."""
    global _control_event_sink
    _control_event_sink = None
