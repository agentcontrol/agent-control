from __future__ import annotations

import json
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
    agent_name,
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
        agent_name=agent_name,
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

    agent_name = f"agent-{uuid4().hex[:12]}"
    now = datetime.now(UTC)

    events = [
        _event(
            agent_name=agent_name,
            control_id=1,
            action="observe",
            matched=True,
            timestamp=now - timedelta(seconds=10),
            trace_id="a" * 32,
        ),
        _event(
            agent_name=agent_name,
            control_id=2,
            action="deny",
            matched=False,
            timestamp=now - timedelta(seconds=5),
            trace_id="b" * 32,
        ),
        _event(
            agent_name=agent_name,
            control_id=1,
            action="observe",
            matched=True,
            timestamp=now,
            trace_id="a" * 32,
        ),
    ]

    # When: storing events
    await store.store(events)

    # When: querying events filtered by control_id
    query = EventQueryRequest(agent_name=agent_name, control_ids=[1], limit=10, offset=0)
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
    stats = await store.query_stats(agent_name, timedelta(hours=1))
    # Then: totals and action counts are aggregated correctly
    assert stats.total_executions == 3
    assert stats.total_matches == 2
    assert stats.total_non_matches == 1
    assert stats.total_errors == 0
    assert stats.action_counts == {"observe": 2}

    # When: querying stats with a control filter
    filtered_stats = await store.query_stats(agent_name, timedelta(hours=1), control_id=1)
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

    agent_name = f"agent-{uuid4().hex[:12]}"
    other_agent = f"agent-{uuid4().hex[:12]}"
    now = datetime.now(UTC)

    target_exec_id = "exec-1"
    target_span_id = "span-1"
    target_trace_id = "a" * 32

    events = [
        _event(
            agent_name=agent_name,
            control_id=1,
            action="observe",
            matched=True,
            timestamp=now - timedelta(seconds=1),
            trace_id=target_trace_id,
            span_id=target_span_id,
            control_execution_id=target_exec_id,
            check_stage="pre",
            applies_to="llm_call",
        ),
        _event(
            agent_name=other_agent,
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
        agent_name=agent_name,
        start_time=now - timedelta(seconds=2),
        end_time=now,
        trace_id=target_trace_id,
        span_id=target_span_id,
        control_ids=[1],
        actions=["observe"],
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
async def test_postgres_event_store_normalizes_legacy_advisory_rows() -> None:
    # Given: a historical event row stored with a legacy advisory action name
    session_maker = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    store = PostgresEventStore(session_maker)

    agent_name = f"agent-{uuid4().hex[:12]}"
    now = datetime.now(UTC)
    event = _event(
        agent_name=agent_name,
        control_id=7,
        action="observe",
        matched=True,
        timestamp=now,
        trace_id="d" * 32,
    )
    legacy_payload = event.model_dump(mode="json")
    legacy_payload["action"] = "warn"

    async with session_maker() as session:
        await session.execute(
            text("""
                INSERT INTO control_execution_events (
                    control_execution_id, timestamp, agent_name, data
                ) VALUES (
                    :control_execution_id, :timestamp, :agent_name, CAST(:data AS JSONB)
                )
            """),
            {
                "control_execution_id": event.control_execution_id,
                "timestamp": event.timestamp,
                "agent_name": event.agent_name,
                "data": json.dumps(legacy_payload),
            },
        )
        await session.commit()

    # When: querying with the canonical observe filter
    resp = await store.query_events(
        EventQueryRequest(agent_name=agent_name, actions=["observe"], limit=10, offset=0)
    )
    stats = await store.query_stats(agent_name, timedelta(hours=1))

    # Then: the legacy row is returned and normalized to observe
    assert resp.total == 1
    assert resp.events[0].action == "observe"
    assert stats.action_counts == {"observe": 1}


@pytest.mark.asyncio
async def test_postgres_event_store_timeseries_includes_steer_and_observe_counts() -> None:
    # Given: a Postgres-backed store with steer and advisory events
    session_maker = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    store = PostgresEventStore(session_maker)

    agent_name = f"agent-{uuid4().hex[:12]}"
    now = datetime.now(UTC)

    events = [
        _event(
            agent_name=agent_name,
            control_id=1,
            action="steer",
            matched=True,
            timestamp=now - timedelta(seconds=10),
            trace_id="a" * 32,
        ),
        _event(
            agent_name=agent_name,
            control_id=2,
            action="observe",
            matched=True,
            timestamp=now - timedelta(seconds=5),
            trace_id="b" * 32,
        ),
        _event(
            agent_name=agent_name,
            control_id=3,
            action="observe",
            matched=True,
            timestamp=now,
            trace_id="c" * 32,
        ),
    ]

    # When: storing events
    await store.store(events)

    # When: querying stats with timeseries enabled
    stats = await store.query_stats(
        agent_name,
        time_range=timedelta(hours=1),
        include_timeseries=True,
        bucket_size=timedelta(minutes=1),
    )

    # Then: action counts include steer and observe
    assert stats.action_counts["steer"] == 1
    assert stats.action_counts["observe"] == 2

    # Then: timeseries buckets include steer and observe in their action_counts
    assert stats.timeseries is not None
    all_bucket_actions = [
        action
        for bucket in stats.timeseries
        for action in bucket.action_counts.keys()
    ]
    assert "steer" in all_bucket_actions
    assert "observe" in all_bucket_actions


@pytest.mark.asyncio
async def test_postgres_event_store_parses_string_json_rows() -> None:
    # Given: a store backed by a stub session returning string JSON data
    event = ControlExecutionEvent(
        trace_id="a" * 32,
        span_id="b" * 16,
                agent_name="agent-test-01",
        control_id=1,
        control_name="control-1",
        check_stage="pre",
        applies_to="llm_call",
        action="observe",
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
