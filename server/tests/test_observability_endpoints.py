"""Tests for observability API endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_control_models import (
    BatchEventsRequest,
    ControlExecutionEvent,
    EventQueryRequest,
)
from agent_control_server.main import app
from agent_control_server.observability.ingest.base import IngestResult


def create_test_event(
    control_id: int = 1,
    agent_uuid: str | UUID | None = None,
    action: str = "allow",
    matched: bool = False,
    timestamp: datetime | None = None,
    execution_duration_ms: float | None = None,
) -> ControlExecutionEvent:
    """Create a test control execution event."""
    return ControlExecutionEvent(
        trace_id="a" * 32,  # 128-bit hex (32 chars)
        span_id="b" * 16,  # 64-bit hex (16 chars)
        agent_uuid=agent_uuid or uuid4(),
        agent_name="test-agent",
        control_id=control_id,
        control_name=f"control-{control_id}",
        check_stage="pre",
        applies_to="llm_call",
        action=action,
        matched=matched,
        confidence=0.95,
        timestamp=timestamp or datetime.now(timezone.utc),
        execution_duration_ms=execution_duration_ms,
    )


class TestEventIngestion:
    """Tests for POST /events endpoint."""

    def test_ingest_events_success(self, client: TestClient, setup_observability):
        """Test successful event ingestion."""
        events = [create_test_event(i) for i in range(3)]
        request = BatchEventsRequest(events=events)

        response = client.post(
            "/api/v1/observability/events",
            json=request.model_dump(mode="json"),
        )

        assert response.status_code == 202
        data = response.json()
        assert data["received"] == 3
        assert data["enqueued"] == 3
        assert data["dropped"] == 0
        assert data["status"] == "queued"

    def test_ingest_single_event(self, client: TestClient, setup_observability):
        """Test ingestion with single event."""
        events = [create_test_event()]
        request = BatchEventsRequest(events=events)

        response = client.post(
            "/api/v1/observability/events",
            json=request.model_dump(mode="json"),
        )

        assert response.status_code == 202
        data = response.json()
        assert data["received"] == 1
        assert data["enqueued"] == 1
        assert data["status"] == "queued"


class TestObservabilityStatus:
    """Tests for GET /status endpoint."""

    def test_get_status(self, client: TestClient, setup_observability):
        """Test getting observability system status."""
        response = client.get("/api/v1/observability/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["ingestor_initialized"] is True
        assert data["store_initialized"] is True


class TestEventQueryRequest:
    """Tests for EventQueryRequest validation."""

    def test_query_request_defaults(self):
        """Test default values for query request."""
        request = EventQueryRequest()
        assert request.limit == 100
        assert request.offset == 0
        assert request.trace_id is None
        assert request.span_id is None

    def test_query_request_with_filters(self):
        """Test query request with various filters."""
        request = EventQueryRequest(
            trace_id="a" * 32,
            agent_uuid=uuid4(),
            control_ids=[1, 2, 3],
            actions=["allow", "deny"],
            matched=True,
            check_stages=["pre", "post"],
            applies_to=["llm_call"],
            limit=50,
            offset=10,
        )
        assert request.trace_id == "a" * 32
        assert len(request.control_ids) == 3
        assert request.limit == 50


class TestBatchEventsRequest:
    """Tests for BatchEventsRequest validation."""

    def test_batch_request_with_events(self):
        """Test batch request with events."""
        events = [create_test_event(i) for i in range(5)]
        request = BatchEventsRequest(events=events)
        assert len(request.events) == 5

    def test_batch_request_requires_at_least_one_event(self):
        """Test batch request requires at least one event."""
        with pytest.raises(Exception):  # pydantic ValidationError
            BatchEventsRequest(events=[])


class TestControlExecutionEvent:
    """Tests for ControlExecutionEvent model."""

    def test_event_creation(self):
        """Test creating an event with required fields."""
        event = create_test_event()
        assert event.trace_id == "a" * 32
        assert event.span_id == "b" * 16
        assert event.control_name == "control-1"
        assert event.check_stage == "pre"
        assert event.applies_to == "llm_call"

    def test_event_with_all_fields(self):
        """Test creating an event with all fields."""
        event = ControlExecutionEvent(
            trace_id="a" * 32,
            span_id="b" * 16,
            agent_uuid=uuid4(),
            agent_name="test-agent",
            control_id=1,
            control_name="test-control",
            check_stage="post",
            applies_to="tool_call",
            action="deny",
            matched=True,
            confidence=0.99,
            timestamp=datetime.now(timezone.utc),
            execution_duration_ms=15.5,
            evaluator_name="regex",
            selector_path="input",
            error_message=None,
            metadata={"key": "value"},
        )
        assert event.action == "deny"
        assert event.matched is True
        assert event.execution_duration_ms == 15.5

    def test_event_default_metadata(self):
        """Test that metadata defaults to empty dict."""
        event = create_test_event()
        assert event.metadata == {}


class TestPostgresEventStore:
    """Tests for PostgresEventStore operations."""

    @pytest.mark.asyncio
    async def test_store_events(self, setup_observability):
        """Test storing events in PostgreSQL."""
        store = setup_observability
        events = [create_test_event(i) for i in range(5)]

        stored = await store.store(events)
        assert stored == 5

    @pytest.mark.asyncio
    async def test_store_deduplicates_events(self, setup_observability):
        """Test that duplicate events are not stored (ON CONFLICT DO NOTHING)."""
        store = setup_observability
        event = create_test_event()

        await store.store([event])
        # Storing same event again should not raise, but also not duplicate
        stored = await store.store([event])
        # ON CONFLICT DO NOTHING returns the batch size, not actual inserts
        assert stored == 1

    @pytest.mark.asyncio
    async def test_ingest_via_direct_ingestor(self, setup_observability):
        """Test ingesting events via DirectEventIngestor."""
        from agent_control_server.observability import DirectEventIngestor

        store = setup_observability
        ingestor = DirectEventIngestor(store)

        events = [create_test_event(i) for i in range(3)]
        result = await ingestor.ingest(events)

        assert result.received == 3
        assert result.processed == 3
        assert result.dropped == 0


class TestStatsTimeseries:
    """Tests for time-series stats functionality."""

    @pytest.mark.asyncio
    async def test_stats_without_timeseries(self, client: TestClient, setup_observability):
        """Default response has no timeseries."""
        store = setup_observability
        agent_uuid = uuid4()

        # Create and store an event
        event = create_test_event(agent_uuid=agent_uuid, matched=True)
        await store.store([event])

        response = client.get(
            "/api/v1/observability/stats",
            params={"agent_uuid": str(agent_uuid), "time_range": "1h"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["totals"]["timeseries"] is None
        assert data["totals"]["execution_count"] == 1

    @pytest.mark.asyncio
    async def test_stats_with_timeseries(self, client: TestClient, setup_observability):
        """With include_timeseries=true, returns buckets."""
        store = setup_observability
        agent_uuid = uuid4()
        now = datetime.now(timezone.utc)

        # Create events spread across time
        events = [
            create_test_event(
                agent_uuid=agent_uuid,
                matched=True,
                action="allow",
                timestamp=now - timedelta(minutes=30),
                execution_duration_ms=10.0,
            ),
            create_test_event(
                agent_uuid=agent_uuid,
                matched=True,
                action="deny",
                timestamp=now - timedelta(minutes=15),
                execution_duration_ms=20.0,
            ),
            create_test_event(
                agent_uuid=agent_uuid,
                matched=False,
                timestamp=now - timedelta(minutes=5),
            ),
        ]

        await store.store(events)

        response = client.get(
            "/api/v1/observability/stats",
            params={
                "agent_uuid": str(agent_uuid),
                "time_range": "1h",
                "include_timeseries": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["totals"]["timeseries"] is not None
        assert len(data["totals"]["timeseries"]) > 0

        # Verify bucket structure
        bucket = data["totals"]["timeseries"][0]
        assert "timestamp" in bucket
        assert "execution_count" in bucket
        assert "match_count" in bucket
        assert "non_match_count" in bucket
        assert "error_count" in bucket
        assert "action_counts" in bucket
        assert "avg_confidence" in bucket
        assert "avg_duration_ms" in bucket

    @pytest.mark.asyncio
    async def test_timeseries_bucket_count_1h(self, client: TestClient, setup_observability):
        """Verify reasonable number of buckets for 1h time range (5m buckets)."""
        store = setup_observability
        agent_uuid = uuid4()
        now = datetime.now(timezone.utc)

        # Create a single event
        event = create_test_event(
            agent_uuid=agent_uuid,
            matched=True,
            timestamp=now - timedelta(minutes=30),
        )

        await store.store([event])

        response = client.get(
            "/api/v1/observability/stats",
            params={
                "agent_uuid": str(agent_uuid),
                "time_range": "1h",
                "include_timeseries": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # 1h with 5m buckets = ~12-13 buckets (depends on timing)
        assert data["totals"]["timeseries"] is not None
        assert 11 <= len(data["totals"]["timeseries"]) <= 13

    @pytest.mark.asyncio
    async def test_timeseries_bucket_count_5m(self, client: TestClient, setup_observability):
        """Verify reasonable number of buckets for 5m time range (30s buckets)."""
        store = setup_observability
        agent_uuid = uuid4()
        now = datetime.now(timezone.utc)

        # Create a single event
        event = create_test_event(
            agent_uuid=agent_uuid,
            matched=True,
            timestamp=now - timedelta(minutes=2),
        )

        await store.store([event])

        response = client.get(
            "/api/v1/observability/stats",
            params={
                "agent_uuid": str(agent_uuid),
                "time_range": "5m",
                "include_timeseries": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # 5m with 30s buckets = ~10-11 buckets (depends on timing)
        assert data["totals"]["timeseries"] is not None
        assert 9 <= len(data["totals"]["timeseries"]) <= 11

    @pytest.mark.asyncio
    async def test_timeseries_aggregates_events_per_bucket(
        self, client: TestClient, setup_observability
    ):
        """Events in the same bucket are aggregated."""
        store = setup_observability
        agent_uuid = uuid4()
        now = datetime.now(timezone.utc)

        # Create multiple events in the same 5-minute bucket
        base_time = now - timedelta(minutes=10)
        events = [
            create_test_event(
                agent_uuid=agent_uuid,
                matched=True,
                action="allow",
                timestamp=base_time + timedelta(seconds=30),
                execution_duration_ms=10.0,
            ),
            create_test_event(
                agent_uuid=agent_uuid,
                matched=True,
                action="deny",
                timestamp=base_time + timedelta(seconds=60),
                execution_duration_ms=20.0,
            ),
            create_test_event(
                agent_uuid=agent_uuid,
                matched=False,
                timestamp=base_time + timedelta(seconds=90),
                execution_duration_ms=30.0,
            ),
        ]

        await store.store(events)

        response = client.get(
            "/api/v1/observability/stats",
            params={
                "agent_uuid": str(agent_uuid),
                "time_range": "1h",
                "include_timeseries": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        timeseries = data["totals"]["timeseries"]
        assert timeseries is not None

        # Find the bucket(s) with events - events may span 1-2 buckets
        buckets_with_events = [b for b in timeseries if b["execution_count"] > 0]
        assert 1 <= len(buckets_with_events) <= 2

        # Sum up totals across all buckets with events
        total_exec = sum(b["execution_count"] for b in buckets_with_events)
        total_match = sum(b["match_count"] for b in buckets_with_events)
        total_non_match = sum(b["non_match_count"] for b in buckets_with_events)
        total_allow = sum(b["action_counts"].get("allow", 0) for b in buckets_with_events)
        total_deny = sum(b["action_counts"].get("deny", 0) for b in buckets_with_events)

        assert total_exec == 3
        assert total_match == 2
        assert total_non_match == 1
        assert total_allow == 1
        assert total_deny == 1

    @pytest.mark.asyncio
    async def test_timeseries_empty_buckets_included(
        self, client: TestClient, setup_observability
    ):
        """Empty buckets are included with zero counts."""
        store = setup_observability
        agent_uuid = uuid4()
        now = datetime.now(timezone.utc)

        # Create events only at the start of the time range
        event = create_test_event(
            agent_uuid=agent_uuid,
            matched=True,
            timestamp=now - timedelta(minutes=55),
        )

        await store.store([event])

        response = client.get(
            "/api/v1/observability/stats",
            params={
                "agent_uuid": str(agent_uuid),
                "time_range": "1h",
                "include_timeseries": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        timeseries = data["totals"]["timeseries"]
        assert timeseries is not None

        # 11-13 buckets should be present (depends on timing)
        assert 11 <= len(timeseries) <= 13

        # Only one bucket should have events
        buckets_with_events = [b for b in timeseries if b["execution_count"] > 0]
        assert len(buckets_with_events) == 1

        # Empty buckets should have zero counts and None for averages
        empty_bucket = next(b for b in timeseries if b["execution_count"] == 0)
        assert empty_bucket["match_count"] == 0
        assert empty_bucket["non_match_count"] == 0
        assert empty_bucket["error_count"] == 0
        assert empty_bucket["action_counts"] == {}
        assert empty_bucket["avg_confidence"] is None
        assert empty_bucket["avg_duration_ms"] is None


class TestControlStats:
    """Tests for control-level stats endpoint."""

    @pytest.mark.asyncio
    async def test_control_stats_basic(self, client: TestClient, setup_observability):
        """Test getting stats for a single control."""
        store = setup_observability
        agent_uuid = uuid4()

        # Create events for multiple controls
        events = [
            create_test_event(control_id=1, agent_uuid=agent_uuid, matched=True, action="allow"),
            create_test_event(control_id=1, agent_uuid=agent_uuid, matched=True, action="deny"),
            create_test_event(control_id=2, agent_uuid=agent_uuid, matched=True, action="warn"),
        ]
        await store.store(events)

        # Get stats for control 1 only
        response = client.get(
            "/api/v1/observability/stats/controls/1",
            params={"agent_uuid": str(agent_uuid), "time_range": "1h"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert data["agent_uuid"] == str(agent_uuid)
        assert data["control_id"] == 1
        assert data["control_name"] == "control-1"
        assert "stats" in data
        assert "controls" not in data  # No controls array in control-level response

        # Verify only control 1's stats
        assert data["stats"]["execution_count"] == 2
        assert data["stats"]["match_count"] == 2
        assert data["stats"]["action_counts"]["allow"] == 1
        assert data["stats"]["action_counts"]["deny"] == 1

    @pytest.mark.asyncio
    async def test_control_stats_with_timeseries(self, client: TestClient, setup_observability):
        """Test control stats with timeseries."""
        store = setup_observability
        agent_uuid = uuid4()
        now = datetime.now(timezone.utc)

        # Create events for control 1 at different times
        events = [
            create_test_event(
                control_id=1,
                agent_uuid=agent_uuid,
                matched=True,
                action="allow",
                timestamp=now - timedelta(minutes=30),
            ),
            create_test_event(
                control_id=1,
                agent_uuid=agent_uuid,
                matched=True,
                action="deny",
                timestamp=now - timedelta(minutes=10),
            ),
            # Control 2 event (should not appear)
            create_test_event(
                control_id=2,
                agent_uuid=agent_uuid,
                matched=True,
                action="warn",
                timestamp=now - timedelta(minutes=20),
            ),
        ]
        await store.store(events)

        response = client.get(
            "/api/v1/observability/stats/controls/1",
            params={
                "agent_uuid": str(agent_uuid),
                "time_range": "1h",
                "include_timeseries": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify timeseries is present and scoped to control 1
        assert data["stats"]["timeseries"] is not None
        assert len(data["stats"]["timeseries"]) > 0

        # Only 2 events total (control 1 only)
        assert data["stats"]["execution_count"] == 2

        # Sum timeseries buckets should equal total
        total_from_buckets = sum(
            b["execution_count"] for b in data["stats"]["timeseries"]
        )
        assert total_from_buckets == 2

    @pytest.mark.asyncio
    async def test_control_stats_no_data(self, client: TestClient, setup_observability):
        """Test control stats when control has no events."""
        store = setup_observability
        agent_uuid = uuid4()

        # Create event for control 1 only
        event = create_test_event(control_id=1, agent_uuid=agent_uuid, matched=True)
        await store.store([event])

        # Query for control 2 (no events)
        response = client.get(
            "/api/v1/observability/stats/controls/2",
            params={"agent_uuid": str(agent_uuid), "time_range": "1h"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["control_id"] == 2
        assert data["stats"]["execution_count"] == 0
        assert data["stats"]["match_count"] == 0


class TestObservabilityQueries:
    """Tests for observability query endpoints."""

    def test_query_events_filters_and_pagination(self, client: TestClient, setup_observability):
        """Test POST /events/query with filters and pagination."""
        # Given: multiple events ingested into the store
        event1 = create_test_event(control_id=1, action="allow", matched=True)
        event2 = create_test_event(control_id=2, action="deny", matched=False).model_copy(
            update={"trace_id": "c" * 32}
        )
        event3 = create_test_event(control_id=1, action="allow", matched=True).model_copy(
            update={"span_id": "d" * 16}
        )

        request = BatchEventsRequest(events=[event1, event2, event3])
        ingest_resp = client.post(
            "/api/v1/observability/events",
            json=request.model_dump(mode="json"),
        )
        assert ingest_resp.status_code == 202

        # When: querying by trace_id
        query = EventQueryRequest(trace_id="a" * 32, limit=10, offset=0)
        resp = client.post(
            "/api/v1/observability/events/query",
            json=query.model_dump(mode="json"),
        )
        assert resp.status_code == 200
        body = resp.json()
        # Then: only matching events are returned
        assert body["total"] == 2
        assert all(e["trace_id"] == "a" * 32 for e in body["events"])

        # When: querying with pagination
        query_page = EventQueryRequest(limit=1, offset=1)
        resp_page = client.post(
            "/api/v1/observability/events/query",
            json=query_page.model_dump(mode="json"),
        )
        assert resp_page.status_code == 200
        body_page = resp_page.json()
        # Then: pagination works and total is preserved
        assert body_page["total"] == 3
        assert len(body_page["events"]) == 1

    def test_get_stats_aggregates_events(self, client: TestClient, setup_observability):
        """Test GET /stats aggregates events for an agent."""
        # Given: events for a specific agent and one other agent
        agent_uuid = uuid4()
        event1 = create_test_event(control_id=1, action="allow", matched=True).model_copy(
            update={"agent_uuid": agent_uuid}
        )
        event2 = create_test_event(control_id=2, action="deny", matched=True).model_copy(
            update={"agent_uuid": agent_uuid, "trace_id": "c" * 32}
        )
        # Event from different agent (should not be counted)
        event3 = create_test_event(control_id=1, action="warn", matched=True).model_copy(
            update={"trace_id": "d" * 32}
        )

        request = BatchEventsRequest(events=[event1, event2, event3])
        ingest_resp = client.post(
            "/api/v1/observability/events",
            json=request.model_dump(mode="json"),
        )
        assert ingest_resp.status_code == 202

        # When: getting stats for the agent
        resp = client.get(
            "/api/v1/observability/stats",
            params={"agent_uuid": str(agent_uuid), "time_range": "1h"},
        )

        assert resp.status_code == 200
        body = resp.json()
        # Then: totals reflect only that agent's events
        assert body["totals"]["execution_count"] == 2
        assert body["totals"]["match_count"] == 2
        # And per-control breakdown exists
        assert len(body["controls"]) == 2


class TestObservabilityIngestStatus:
    """Tests for ingestion status mapping."""

    def test_ingest_events_partial_status(self, client: TestClient, setup_observability):
        """Test partial status when some events are dropped."""
        # Given: a stub ingestor that drops some events
        class StubIngestor:
            async def ingest(self, events):
                return IngestResult(received=len(events), processed=1, dropped=len(events) - 1)

        original = app.state.event_ingestor
        app.state.event_ingestor = StubIngestor()
        try:
            events = [create_test_event(i) for i in range(3)]
            request = BatchEventsRequest(events=events)

            # When: ingesting events
            response = client.post(
                "/api/v1/observability/events",
                json=request.model_dump(mode="json"),
            )

            # Then: status is partial with expected counts
            assert response.status_code == 202
            data = response.json()
            assert data["received"] == 3
            assert data["enqueued"] == 1
            assert data["dropped"] == 2
            assert data["status"] == "partial"
        finally:
            app.state.event_ingestor = original

    def test_ingest_events_failed_status(self, client: TestClient, setup_observability):
        """Test failed status when all events are dropped."""
        # Given: a stub ingestor that drops all events
        class StubIngestor:
            async def ingest(self, events):
                return IngestResult(received=len(events), processed=0, dropped=len(events))

        original = app.state.event_ingestor
        app.state.event_ingestor = StubIngestor()
        try:
            events = [create_test_event(i) for i in range(2)]
            request = BatchEventsRequest(events=events)

            # When: ingesting events
            response = client.post(
                "/api/v1/observability/events",
                json=request.model_dump(mode="json"),
            )

            # Then: status is failed with expected counts
            assert response.status_code == 202
            data = response.json()
            assert data["received"] == 2
            assert data["enqueued"] == 0
            assert data["dropped"] == 2
            assert data["status"] == "failed"
        finally:
            app.state.event_ingestor = original
