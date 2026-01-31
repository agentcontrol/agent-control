from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from agent_control_models.observability import ControlExecutionEvent, EventQueryRequest
from agent_control_server.observability.store.memory import MemoryEventStore


def _event(
    *,
    agent_uuid=None,
    control_execution_id: str | None = None,
    control_id: int = 1,
    action: str = "allow",
    matched: bool = True,
    error_message: str | None = None,
    timestamp: datetime | None = None,
    trace_id: str = "a" * 32,
    span_id: str = "b" * 16,
    check_stage: str = "pre",
    applies_to: str = "llm_call",
    confidence: float = 0.9,
    execution_duration_ms: float | None = None,
) -> ControlExecutionEvent:
    return ControlExecutionEvent(
        trace_id=trace_id,
        span_id=span_id,
        agent_uuid=agent_uuid or uuid4(),
        agent_name="agent",
        control_id=control_id,
        control_name=f"control-{control_id}",
        check_stage=check_stage,
        applies_to=applies_to,
        action=action,
        matched=matched,
        confidence=confidence,
        timestamp=timestamp or datetime.now(UTC),
        execution_duration_ms=execution_duration_ms,
        error_message=error_message,
        control_execution_id=control_execution_id or str(uuid4()),
    )


@pytest.mark.asyncio
async def test_memory_event_store_query_stats() -> None:
    # Given: a store with multiple events across controls and outcomes
    store = MemoryEventStore()
    agent_uuid = uuid4()
    now = datetime.now(UTC)

    events = [
        _event(agent_uuid=agent_uuid, control_id=1, action="allow", matched=True, timestamp=now),
        _event(agent_uuid=agent_uuid, control_id=1, action="allow", matched=False, timestamp=now),
        _event(
            agent_uuid=agent_uuid,
            control_id=1,
            action="allow",
            matched=True,
            error_message="boom",
            timestamp=now,
        ),
        _event(
            agent_uuid=agent_uuid,
            control_id=2,
            action="deny",
            matched=True,
            execution_duration_ms=12.5,
            timestamp=now,
        ),
    ]

    # When: storing events and querying stats
    await store.store(events)

    result = await store.query_stats(agent_uuid, timedelta(hours=1))

    # Then: totals and action counts are aggregated correctly
    assert result.total_executions == 4
    assert result.total_matches == 2
    assert result.total_non_matches == 1
    assert result.total_errors == 1
    assert result.action_counts == {"allow": 2, "deny": 1}

    # Then: per-control stats are sorted by execution count desc
    assert result.stats[0].control_id == 1
    assert result.stats[0].execution_count == 3
    assert result.stats[1].control_id == 2
    assert result.stats[1].execution_count == 1

    # When: filtering by control_id
    result_control = await store.query_stats(agent_uuid, timedelta(hours=1), control_id=2)
    # Then: only the requested control is returned
    assert len(result_control.stats) == 1
    assert result_control.stats[0].control_id == 2


@pytest.mark.asyncio
async def test_memory_event_store_query_events_filters_and_pagination() -> None:
    # Given: a store with several events and varying fields
    store = MemoryEventStore()
    agent_uuid = uuid4()
    now = datetime.now(UTC)

    e1 = _event(
        agent_uuid=agent_uuid,
        control_id=1,
        action="allow",
        matched=True,
        trace_id="a" * 32,
        span_id="b" * 16,
        timestamp=now - timedelta(seconds=10),
        check_stage="pre",
        applies_to="llm_call",
    )
    e2 = _event(
        agent_uuid=agent_uuid,
        control_id=2,
        action="deny",
        matched=False,
        trace_id="c" * 32,
        span_id="d" * 16,
        timestamp=now - timedelta(seconds=5),
        check_stage="post",
        applies_to="tool_call",
    )
    e3 = _event(
        agent_uuid=agent_uuid,
        control_id=1,
        action="allow",
        matched=True,
        trace_id="a" * 32,
        span_id="e" * 16,
        timestamp=now,
        check_stage="pre",
        applies_to="llm_call",
    )

    await store.store([e1, e2, e3])

    # When: filtering by trace_id
    query = EventQueryRequest(trace_id="a" * 32, limit=10, offset=0)
    resp = await store.query_events(query)
    # Then: only matching events are returned in timestamp desc order
    assert resp.total == 2
    assert all(e.trace_id == "a" * 32 for e in resp.events)
    # Sorted by timestamp desc
    assert resp.events[0].timestamp >= resp.events[1].timestamp

    # When: filtering by action + matched
    query = EventQueryRequest(actions=["deny"], matched=False, limit=10, offset=0)
    resp = await store.query_events(query)
    # Then: only matching events are returned
    assert resp.total == 1
    assert resp.events[0].control_id == 2

    # When: filtering by time range
    query = EventQueryRequest(
        start_time=now - timedelta(seconds=6),
        end_time=now,
        limit=10,
        offset=0,
    )
    resp = await store.query_events(query)
    # Then: only events in range are returned
    assert resp.total == 2

    # When: paginating
    query = EventQueryRequest(limit=1, offset=1)
    resp = await store.query_events(query)
    # Then: pagination returns one event and total remains accurate
    assert resp.total == 3
    assert len(resp.events) == 1


@pytest.mark.asyncio
async def test_memory_event_store_query_events_additional_filters() -> None:
    # Given: a store with events differing by id, agent, stage, and scope
    store = MemoryEventStore()
    agent_uuid = uuid4()
    other_agent = uuid4()

    e1 = _event(
        agent_uuid=agent_uuid,
        control_execution_id="exec-1",
        control_id=10,
        span_id="span-1",
        check_stage="pre",
        applies_to="llm_call",
    )
    e2 = _event(
        agent_uuid=other_agent,
        control_execution_id="exec-2",
        control_id=20,
        span_id="span-2",
        check_stage="post",
        applies_to="tool_call",
    )

    await store.store([e1, e2])

    # When: filtering on span_id, control_execution_id, agent, control_ids, and stage/scope
    query = EventQueryRequest(
        span_id="span-1",
        control_execution_id="exec-1",
        agent_uuid=agent_uuid,
        control_ids=[10],
        check_stages=["pre"],
        applies_to=["llm_call"],
        limit=10,
        offset=0,
    )
    resp = await store.query_events(query)

    # Then: only the matching event is returned
    assert resp.total == 1
    assert resp.events[0].control_execution_id == "exec-1"
