"""Server-side sink implementations for observability event delivery."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_control_models.observability import ControlExecutionEvent
from agent_control_telemetry import (
    DEFAULT_CONTROL_EVENT_SINK_NAME,
    REGISTERED_CONTROL_EVENT_SINK_NAME,
    AsyncControlEventSink,
    ControlEventSinkFactory,
    ControlEventSinkFactoryRegistry,
    ControlEventSinkSelection,
    SinkResult,
)
from agent_control_telemetry.sink_selection import SinkSelectionError

from .store.base import EventStore

_named_event_sink_factories: ControlEventSinkFactoryRegistry[ResolvedControlEventBackend] = (
    ControlEventSinkFactoryRegistry()
)


class EventStoreControlEventSink:
    """Write events through an EventStore-backed sink."""

    def __init__(self, store: EventStore):
        self.store = store

    async def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        """Write events to the underlying store and report accepted/dropped counts."""
        stored = await self.store.store(list(events))
        dropped = max(len(events) - stored, 0)
        return SinkResult(accepted=stored, dropped=dropped)


@dataclass(frozen=True)
class ResolvedControlEventBackend:
    """Server observability backend with aligned write and query dependencies."""

    sink: AsyncControlEventSink
    event_store: EventStore


def register_control_event_sink_factory(
    name: str,
    factory: ControlEventSinkFactory[ResolvedControlEventBackend],
) -> None:
    """Register a named server observability backend factory for sink selection."""
    _named_event_sink_factories.register(name, factory)


def unregister_control_event_sink_factory(name: str) -> None:
    """Unregister a named async control-event sink factory."""
    _named_event_sink_factories.unregister(name)


def get_registered_control_event_sink_factory_names() -> tuple[str, ...]:
    """Return the registered named server sink factories."""
    return _named_event_sink_factories.registered_names()


def resolve_control_event_backend(
    selection: ControlEventSinkSelection,
    *,
    default_backend: ResolvedControlEventBackend | None = None,
) -> ResolvedControlEventBackend:
    """Resolve the active server observability backend from shared selection config.

    The shared ``ControlEventSinkSelection`` model provides only the config
    shape. Server-specific built-in semantics are defined here, so SDK-only
    selections such as ``registered`` are rejected explicitly.
    """
    if selection.name == DEFAULT_CONTROL_EVENT_SINK_NAME:
        if default_backend is None:
            raise RuntimeError("Default server observability backend was not provided")
        return default_backend
    if selection.name == REGISTERED_CONTROL_EVENT_SINK_NAME:
        raise RuntimeError(
            "The 'registered' observability sink is not supported on the server; "
            "configure 'default' or a named server sink factory instead"
        )

    try:
        return _named_event_sink_factories.resolve(selection)
    except SinkSelectionError as exc:
        raise RuntimeError(str(exc)) from exc
