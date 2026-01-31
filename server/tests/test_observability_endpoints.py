"""Tests for observability API endpoints."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_control_models import (
    BatchEventsRequest,
    ControlExecutionEvent,
    EventQueryRequest,
)
from agent_control_server.main import app
from agent_control_server.observability import (
    DirectEventIngestor,
    MemoryEventStore,
)
from agent_control_server.observability.ingest.base import IngestResult


def create_test_event(
    control_id: int = 1,
    agent_uuid: str | None = None,
    action: str = "allow",
    matched: bool = False,
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
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def setup_memory_store():
    """Set up in-memory store for each test via app.state."""
    store = MemoryEventStore()
    ingestor = DirectEventIngestor(store)
    app.state.event_store = store
    app.state.event_ingestor = ingestor
    yield store
    store.clear()
    # Clean up app.state
    del app.state.event_store
    del app.state.event_ingestor


class TestEventIngestion:
    """Tests for POST /events endpoint."""

    def test_ingest_events_success(self, client: TestClient):
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

    def test_ingest_single_event(self, client: TestClient):
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

    def test_get_status(self, client: TestClient):
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


class TestMemoryEventStore:
    """Tests for MemoryEventStore operations."""

    @pytest.mark.asyncio
    async def test_store_events(self, setup_memory_store):
        """Test storing events in memory store."""
        store = setup_memory_store
        events = [create_test_event(i) for i in range(5)]

        stored = await store.store(events)
        assert stored == 5
        assert store.event_count == 5

    @pytest.mark.asyncio
    async def test_store_deduplicates_events(self, setup_memory_store):
        """Test that duplicate events are not stored."""
        store = setup_memory_store
        event = create_test_event()

        await store.store([event])
        await store.store([event])  # Same event

        assert store.event_count == 1

    @pytest.mark.asyncio
    async def test_ingest_via_direct_ingestor(self, setup_memory_store):
        """Test ingesting events via DirectEventIngestor."""
        store = setup_memory_store
        ingestor = DirectEventIngestor(store)

        events = [create_test_event(i) for i in range(3)]
        result = await ingestor.ingest(events)

        assert result.received == 3
        assert result.processed == 3
        assert result.dropped == 0
        assert store.event_count == 3


class TestObservabilityQueries:
    """Tests for observability query endpoints."""

    def test_query_events_filters_and_pagination(self, client: TestClient):
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

    def test_get_stats_aggregates_events(self, client: TestClient):
        """Test GET /stats aggregates events for an agent."""
        # Given: events for a specific agent and one other agent
        agent_uuid = uuid4()
        event1 = create_test_event(control_id=1, action="allow", matched=True).model_copy(
            update={"agent_uuid": agent_uuid}
        )
        event2 = create_test_event(control_id=1, action="deny", matched=False).model_copy(
            update={"agent_uuid": agent_uuid}
        )
        event3 = create_test_event(control_id=2, action="deny", matched=True).model_copy(
            update={"agent_uuid": agent_uuid}
        )
        event_other = create_test_event(control_id=3).model_copy(
            update={"agent_uuid": uuid4()}
        )

        request = BatchEventsRequest(events=[event1, event2, event3, event_other])
        ingest_resp = client.post(
            "/api/v1/observability/events",
            json=request.model_dump(mode="json"),
        )
        assert ingest_resp.status_code == 202

        # When: requesting stats for the target agent
        resp = client.get(
            "/api/v1/observability/stats",
            params={"agent_uuid": str(agent_uuid), "time_range": "1h"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Then: stats reflect only that agent's events
        assert body["total_executions"] == 3
        assert body["total_matches"] == 2
        assert body["total_non_matches"] == 1

    def test_query_events_returns_500_when_store_missing(self, client: TestClient):
        """Test that query endpoint fails when the event store is not initialized."""
        # Given: the event store is unset
        original_store = app.state.event_store
        app.state.event_store = None
        try:
            # When: posting a query
            query = EventQueryRequest(limit=10, offset=0)
            with pytest.raises(RuntimeError):
                client.post(
                    "/api/v1/observability/events/query",
                    json=query.model_dump(mode="json"),
                )
        finally:
            app.state.event_store = original_store

        # Then: an internal error is returned
        # (exception raised due to TestClient raise_server_exceptions=True)


class TestObservabilityIngestStatus:
    """Tests for ingestion status mapping."""

    def test_ingest_events_partial_status(self, client: TestClient):
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

    def test_ingest_events_failed_status(self, client: TestClient):
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
