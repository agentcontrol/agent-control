"""Control event delivery interfaces for SDK observability."""

from collections.abc import Callable

from agent_control_models import ControlExecutionEvent

from ..evaluation_events import enqueue_observability_events
from ..observability import get_logger

ControlEventSink = Callable[[list[ControlExecutionEvent]], None]

_control_event_sink: ControlEventSink | None = None
_logger = get_logger(__name__)


def set_control_event_sink(sink: ControlEventSink | None) -> None:
    """Register a custom sink for control event delivery.

    Args:
        sink: Callable that consumes a batch of ``ControlExecutionEvent``
            instances. Pass ``None`` to clear any existing sink.

    Returns:
        None.
    """
    global _control_event_sink
    _control_event_sink = sink


def clear_control_event_sink() -> None:
    """Clear the currently registered control event sink.

    Args:
        None.

    Returns:
        None.
    """
    set_control_event_sink(None)


def has_control_event_sink() -> bool:
    """Return whether a custom control event sink is registered.

    Args:
        None.

    Returns:
        ``True`` when a custom sink is registered, otherwise ``False``.
    """
    return _control_event_sink is not None


def emit_control_events(events: list[ControlExecutionEvent]) -> None:
    """Deliver control events through the configured ingestion path.

    By default, events continue through the existing SDK observability queue.
    When a custom sink is registered, the same created events are delivered to
    that sink instead. Event creation mode remains a separate concern.

    Args:
        events: Control execution events that have already been created.

    Returns:
        None.
    """
    if not events:
        return

    if _control_event_sink is not None:
        try:
            _control_event_sink(events)
        except Exception:
            _logger.exception("Custom control event sink failed while delivering events")
        return

    enqueue_observability_events(events)
