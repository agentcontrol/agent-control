from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_control_models.observability import ControlExecutionEvent, EventQueryRequest
from agent_control_server.observability.store.postgres import PostgresEventStore
from .conftest import async_engine, engine


@pytest.fixture(autouse=True)
def clear_event_table() -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM control_execution_events"))
    yield


def _event(
    *,
    agent_uuid,
    control_id: int,
    action: str,
    matched: bool,
    timestamp: datetime,
    trace_id: str,
    span_id: str = "b" * 16,
    control_execution_id: str | None = None,
    check_stage: str = "pre",
    applies_to: str = "llm_call",
) -> ControlExecutionEvent:
    return ControlExecutionEvent(
        trace_id=trace_id,
        span_id=span_id,
        agent_uuid=agent_uuid,
        agent_name="agent",
        control_id=control_id,
        control_name=f"control-{control_id}",
        check_stage=check_stage,
        applies_to=applies_to,
        action=action,
        matched=matched,
        confidence=0.8,
        timestamp=timestamp,
        control_execution_id=control_execution_id or str(uuid4()),
    )


@pytest.mark.asyncio
async def test_postgres_event_store_query_events_and_stats() -> None:
    # Given: a Postgres-backed store and a set of events
    session_maker = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    store = PostgresEventStore(session_maker)

    agent_uuid = uuid4()
    now = datetime.now(UTC)

    events = [
        _event(
            agent_uuid=agent_uuid,
            control_id=1,
            action="allow",
            matched=True,
            timestamp=now - timedelta(seconds=10),
            trace_id="a" * 32,
        ),
        _event(
            agent_uuid=agent_uuid,
            control_id=2,
            action="deny",
            matched=False,
            timestamp=now - timedelta(seconds=5),
            trace_id="b" * 32,
        ),
        _event(
            agent_uuid=agent_uuid,
            control_id=1,
            action="allow",
            matched=True,
            timestamp=now,
            trace_id="a" * 32,
        ),
    ]

    # When: storing events
    await store.store(events)

    # When: querying events filtered by control_id
    query = EventQueryRequest(agent_uuid=agent_uuid, control_ids=[1], limit=10, offset=0)
    resp = await store.query_events(query)
    # Then: only matching events are returned
    assert resp.total == 2
    assert all(e.control_id == 1 for e in resp.events)

    # When: querying events filtered by trace_id
    query = EventQueryRequest(trace_id="a" * 32, limit=10, offset=0)
    resp = await store.query_events(query)
    # Then: only matching events are returned
    assert resp.total == 2
    assert all(e.trace_id == "a" * 32 for e in resp.events)

    # When: querying stats
    stats = await store.query_stats(agent_uuid, timedelta(hours=1))
    # Then: totals and action counts are aggregated correctly
    assert stats.total_executions == 3
    assert stats.total_matches == 2
    assert stats.total_non_matches == 1
    assert stats.total_errors == 0
    assert stats.action_counts == {"allow": 2}

    # When: querying stats with a control filter
    filtered_stats = await store.query_stats(agent_uuid, timedelta(hours=1), control_id=1)
    # Then: only the requested control is returned
    assert len(filtered_stats.stats) == 1
    assert filtered_stats.stats[0].control_id == 1


@pytest.mark.asyncio
async def test_postgres_event_store_store_empty_returns_zero() -> None:
    # Given: a Postgres-backed store
    session_maker = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    store = PostgresEventStore(session_maker)

    # When: storing an empty event list
    stored = await store.store([])

    # Then: zero events are reported as stored
    assert stored == 0


@pytest.mark.asyncio
async def test_postgres_event_store_query_events_all_filters() -> None:
    # Given: a Postgres-backed store with events across fields
    session_maker = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    store = PostgresEventStore(session_maker)

    agent_uuid = uuid4()
    other_agent = uuid4()
    now = datetime.now(UTC)

    target_exec_id = "exec-1"
    target_span_id = "span-1"
    target_trace_id = "a" * 32

    events = [
        _event(
            agent_uuid=agent_uuid,
            control_id=1,
            action="allow",
            matched=True,
            timestamp=now - timedelta(seconds=1),
            trace_id=target_trace_id,
            span_id=target_span_id,
            control_execution_id=target_exec_id,
            check_stage="pre",
            applies_to="llm_call",
        ),
        _event(
            agent_uuid=other_agent,
            control_id=2,
            action="deny",
            matched=False,
            timestamp=now,
            trace_id="b" * 32,
            span_id="span-2",
            control_execution_id="exec-2",
            check_stage="post",
            applies_to="tool_call",
        ),
    ]

    await store.store(events)

    # When: querying with all supported filters
    query = EventQueryRequest(
        control_execution_id=target_exec_id,
        agent_uuid=agent_uuid,
        start_time=now - timedelta(seconds=2),
        end_time=now,
        trace_id=target_trace_id,
        span_id=target_span_id,
        control_ids=[1],
        actions=["allow"],
        matched=True,
        check_stages=["pre"],
        applies_to=["llm_call"],
        limit=10,
        offset=0,
    )
    resp = await store.query_events(query)

    # Then: only the matching event is returned
    assert resp.total == 1
    assert resp.events[0].control_execution_id == target_exec_id


@pytest.mark.asyncio
async def test_postgres_event_store_parses_string_json_rows() -> None:
    # Given: a store backed by a stub session returning string JSON data
    event = ControlExecutionEvent(
        trace_id="a" * 32,
        span_id="b" * 16,
        agent_uuid=uuid4(),
        agent_name="agent",
        control_id=1,
        control_name="control-1",
        check_stage="pre",
        applies_to="llm_call",
        action="allow",
        matched=True,
        confidence=0.9,
        timestamp=datetime.now(UTC),
    )

    class DummyResult:
        def __init__(self, *, scalar_value=None, rows=None):
            self._scalar_value = scalar_value
            self._rows = rows or []

        def scalar(self):  # type: ignore[no-untyped-def]
            return self._scalar_value

        def fetchall(self):  # type: ignore[no-untyped-def]
            return self._rows

    class DummySession:
        def __init__(self, rows):
            self._rows = rows

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def execute(self, statement, params):  # type: ignore[no-untyped-def]
            sql = str(statement)
            if "COUNT" in sql:
                return DummyResult(scalar_value=len(self._rows))
            return DummyResult(rows=self._rows)

    class DummySessionMaker:
        def __init__(self, rows):
            self._rows = rows

        def __call__(self):  # type: ignore[no-untyped-def]
            return DummySession(self._rows)

    rows = [type("Row", (), {"data": event.model_dump_json()})()]
    store = PostgresEventStore(DummySessionMaker(rows))

    # When: querying events
    resp = await store.query_events(EventQueryRequest(limit=10, offset=0))

    # Then: the JSON string is parsed into ControlExecutionEvent
    assert resp.total == 1
    assert resp.events[0].trace_id == event.trace_id
