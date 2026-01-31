from __future__ import annotations

import logging

import pytest

from uuid import uuid4

from agent_control_models.observability import ControlExecutionEvent
from agent_control_server.observability.ingest.direct import DirectEventIngestor
from agent_control_server.observability.store.base import EventStore


class FailingStore(EventStore):
    async def store(self, events: list[ControlExecutionEvent]) -> int:
        raise RuntimeError("boom")

    async def query_stats(self, agent_uuid, time_range, control_id=None):  # pragma: no cover - not used
        raise NotImplementedError

    async def query_events(self, query):  # pragma: no cover - not used
        raise NotImplementedError


class CountingStore(EventStore):
    def __init__(self) -> None:
        self.calls: list[list[ControlExecutionEvent]] = []

    async def store(self, events: list[ControlExecutionEvent]) -> int:
        self.calls.append(events)
        return len(events)

    async def query_stats(self, agent_uuid, time_range, control_id=None):  # pragma: no cover - not used
        raise NotImplementedError

    async def query_events(self, query):  # pragma: no cover - not used
        raise NotImplementedError


@pytest.mark.asyncio
async def test_direct_ingestor_drops_on_store_error() -> None:
    # Given: an ingestor with a failing store
    ingestor = DirectEventIngestor(store=FailingStore())
    events = [
        ControlExecutionEvent(
            trace_id="a" * 32,
            span_id="b" * 16,
            agent_uuid=uuid4(),
            agent_name="agent",
            control_id=1,
            control_name="c",
            check_stage="pre",
            applies_to="llm_call",
            action="allow",
            matched=True,
            confidence=0.9,
        )
    ]

    # When: ingesting events
    result = await ingestor.ingest(events)

    # Then: all events are dropped
    assert result.received == 1
    assert result.processed == 0
    assert result.dropped == 1


@pytest.mark.asyncio
async def test_direct_ingestor_logs_when_enabled(caplog: pytest.LogCaptureFixture) -> None:
    # Given: an ingestor with logging enabled
    store = CountingStore()
    ingestor = DirectEventIngestor(store=store, log_to_stdout=True)
    event = ControlExecutionEvent(
        trace_id="a" * 32,
        span_id="b" * 16,
        agent_uuid=uuid4(),
        agent_name="agent",
        control_id=1,
        control_name="c",
        check_stage="pre",
        applies_to="llm_call",
        action="allow",
        matched=True,
        confidence=0.9,
    )

    # When: ingesting events
    with caplog.at_level(logging.INFO):
        result = await ingestor.ingest([event])

    # Then: event is stored and a log line is emitted
    assert result.processed == 1
    assert store.calls
    assert any("control_execution" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_direct_ingestor_empty_events_returns_zeroes() -> None:
    # Given: an ingestor with any store
    ingestor = DirectEventIngestor(store=CountingStore())

    # When: ingesting an empty list
    result = await ingestor.ingest([])

    # Then: counts are zeroed
    assert result.received == 0
    assert result.processed == 0
    assert result.dropped == 0


@pytest.mark.asyncio
async def test_direct_ingestor_flush_noop() -> None:
    # Given: an ingestor
    ingestor = DirectEventIngestor(store=CountingStore())

    # When: flushing
    await ingestor.flush()

    # Then: no error is raised
    assert True
