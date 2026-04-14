"""Shared sink contracts for control execution event delivery."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_control_models import ControlExecutionEvent


@dataclass(frozen=True)
class SinkResult:
    """Summarizes the outcome of a sink write attempt."""

    accepted: int
    dropped: int = 0

    @property
    def success(self) -> bool:
        """Return True when at least one event was accepted."""
        return self.accepted > 0


class ControlEventSink(Protocol):
    """Write-side abstraction for delivering control execution events."""

    def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        """Write a batch of control execution events."""


class BaseControlEventSink(ControlEventSink):
    """Minimal helper base for sink implementations."""

    def write_event(self, event: ControlExecutionEvent) -> SinkResult:
        """Write a single control execution event."""
        return self.write_events([event])

    def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        """Write a batch of control execution events."""
        accepted = 0
        dropped = 0
        for event in events:
            result = self.write_event(event)
            accepted += result.accepted
            dropped += result.dropped
        return SinkResult(accepted=accepted, dropped=dropped)


class AsyncControlEventSink(Protocol):
    """Async write-side abstraction for delivering control execution events."""

    async def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        """Write a batch of control execution events."""


class BaseAsyncControlEventSink(AsyncControlEventSink):
    """Minimal async helper base for sink implementations."""

    async def write_event(self, event: ControlExecutionEvent) -> SinkResult:
        """Write a single control execution event."""
        return await self.write_events([event])

    async def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        """Write a batch of control execution events."""
        accepted = 0
        dropped = 0
        for event in events:
            result = await self.write_event(event)
            accepted += result.accepted
            dropped += result.dropped
        return SinkResult(accepted=accepted, dropped=dropped)
