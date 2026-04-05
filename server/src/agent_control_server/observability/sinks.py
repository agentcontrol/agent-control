"""Server-side sink implementations for observability event delivery."""

from __future__ import annotations

from collections.abc import Sequence

from agent_control_models.observability import ControlExecutionEvent
from agent_control_telemetry.sinks import SinkResult

from .store.base import EventStore


class EventStoreControlEventSink:
    """Write events through an EventStore-backed sink."""

    def __init__(self, store: EventStore):
        self.store = store

    async def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        """Write events to the underlying store and report accepted/dropped counts."""
        stored = await self.store.store(list(events))
        dropped = max(len(events) - stored, 0)
        return SinkResult(accepted=stored, dropped=dropped)
