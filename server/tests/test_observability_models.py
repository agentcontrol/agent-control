"""Tests for observability Pydantic and SQLAlchemy models."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_control_models import (
    BatchEventsRequest,
    BatchEventsResponse,
    ControlExecutionEvent,
    ControlStats,
    EventQueryRequest,
    EventQueryResponse,
    StatsRequest,
    StatsResponse,
)


class TestControlExecutionEvent:
    """Tests for ControlExecutionEvent model."""

    def test_valid_event(self):
        """Test creating a valid event."""
        event = ControlExecutionEvent(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            agent_uuid=uuid4(),
            agent_name="test-agent",
            control_id=123,
            control_name="sql-injection-check",
            check_stage="pre",
            applies_to="llm_call",
            action="deny",
            matched=True,
            confidence=0.95,
        )
        assert event.matched is True
        assert event.confidence == 0.95
        assert len(event.trace_id) == 32
        assert len(event.span_id) == 16
        # control_execution_id should be auto-generated
        assert event.control_execution_id is not None

    def test_trace_id_validation_empty(self):
        """Test that trace_id cannot be empty."""
        with pytest.raises(ValidationError) as exc_info:
            ControlExecutionEvent(
                trace_id="",
                span_id="00f067aa0ba902b7",
                agent_uuid=uuid4(),
                agent_name="test-agent",
                control_id=123,
                control_name="test",
                check_stage="pre",
                applies_to="llm_call",
                action="allow",
                matched=False,
                confidence=0.5,
            )
        assert "trace_id" in str(exc_info.value)

    def test_trace_id_accepts_various_formats(self):
        """Test that trace_id accepts various formats for flexibility."""
        # Should accept non-standard formats to support different tracing backends
        event = ControlExecutionEvent(
            trace_id="my-custom-trace-id",  # non-hex, non-32-char
            span_id="my-span",
            agent_uuid=uuid4(),
            agent_name="test-agent",
            control_id=123,
            control_name="test",
            check_stage="pre",
            applies_to="llm_call",
            action="allow",
            matched=False,
            confidence=0.5,
        )
        assert event.trace_id == "my-custom-trace-id"
        assert event.span_id == "my-span"

    def test_span_id_validation_empty(self):
        """Test that span_id cannot be empty."""
        with pytest.raises(ValidationError) as exc_info:
            ControlExecutionEvent(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="",
                agent_uuid=uuid4(),
                agent_name="test-agent",
                control_id=123,
                control_name="test",
                check_stage="pre",
                applies_to="llm_call",
                action="allow",
                matched=False,
                confidence=0.5,
            )
        assert "span_id" in str(exc_info.value)

    def test_confidence_bounds(self):
        """Test that confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            ControlExecutionEvent(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="00f067aa0ba902b7",
                agent_uuid=uuid4(),
                agent_name="test-agent",
                control_id=123,
                control_name="test",
                check_stage="pre",
                applies_to="llm_call",
                action="allow",
                matched=False,
                confidence=1.5,  # > 1.0
            )

    def test_check_stage_values(self):
        """Test that check_stage must be 'pre' or 'post'."""
        with pytest.raises(ValidationError):
            ControlExecutionEvent(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="00f067aa0ba902b7",
                agent_uuid=uuid4(),
                agent_name="test-agent",
                control_id=123,
                control_name="test",
                check_stage="invalid",  # invalid
                applies_to="llm_call",
                action="allow",
                matched=False,
                confidence=0.5,
            )

    def test_action_values(self):
        """Test valid action values."""
        for action in ["allow", "deny", "warn", "log"]:
            event = ControlExecutionEvent(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="00f067aa0ba902b7",
                agent_uuid=uuid4(),
                agent_name="test-agent",
                control_id=123,
                control_name="test",
                check_stage="pre",
                applies_to="llm_call",
                action=action,
                matched=True,
                confidence=0.9,
            )
            assert event.action == action

    def test_timestamp_default(self):
        """Test that timestamp defaults to now (UTC)."""
        event = ControlExecutionEvent(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            agent_uuid=uuid4(),
            agent_name="test-agent",
            control_id=123,
            control_name="test",
            check_stage="pre",
            applies_to="llm_call",
            action="allow",
            matched=False,
            confidence=0.5,
        )
        assert event.timestamp is not None
        # Should be close to now
        assert (datetime.now(timezone.utc) - event.timestamp).total_seconds() < 5

    def test_optional_fields(self):
        """Test that optional fields work correctly."""
        event = ControlExecutionEvent(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            agent_uuid=uuid4(),
            agent_name="test-agent",
            control_id=123,
            control_name="test",
            check_stage="pre",
            applies_to="llm_call",
            action="allow",
            matched=False,
            confidence=0.5,
            execution_duration_ms=15.3,
            evaluator_name="regex",
            selector_path="input",
            error_message=None,
            metadata={"key": "value"},
        )
        assert event.execution_duration_ms == 15.3
        assert event.evaluator_name == "regex"
        assert event.selector_path == "input"
        assert event.metadata == {"key": "value"}

    def test_to_dict(self):
        """Test serialization to dict."""
        agent_uuid = uuid4()
        event = ControlExecutionEvent(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            agent_uuid=agent_uuid,
            agent_name="test-agent",
            control_id=123,
            control_name="test",
            check_stage="pre",
            applies_to="llm_call",
            action="allow",
            matched=False,
            confidence=0.5,
        )
        data = event.to_dict()
        assert data["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert data["agent_uuid"] == agent_uuid
        assert data["matched"] is False


class TestBatchEventsRequest:
    """Tests for BatchEventsRequest model."""

    def test_valid_batch(self):
        """Test creating a valid batch."""
        events = [
            ControlExecutionEvent(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="00f067aa0ba902b7",
                agent_uuid=uuid4(),
                agent_name="test-agent",
                control_id=i,
                control_name=f"control-{i}",
                check_stage="pre",
                applies_to="llm_call",
                action="allow",
                matched=False,
                confidence=0.5,
            )
            for i in range(5)
        ]
        batch = BatchEventsRequest(events=events)
        assert len(batch.events) == 5

    def test_empty_batch_rejected(self):
        """Test that empty batches are rejected."""
        with pytest.raises(ValidationError):
            BatchEventsRequest(events=[])

    def test_max_batch_size(self):
        """Test that batch size is limited to 1000."""
        events = [
            ControlExecutionEvent(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="00f067aa0ba902b7",
                agent_uuid=uuid4(),
                agent_name="test-agent",
                control_id=i,
                control_name=f"control-{i}",
                check_stage="pre",
                applies_to="llm_call",
                action="allow",
                matched=False,
                confidence=0.5,
            )
            for i in range(1001)
        ]
        with pytest.raises(ValidationError):
            BatchEventsRequest(events=events)


class TestBatchEventsResponse:
    """Tests for BatchEventsResponse model."""

    def test_valid_response(self):
        """Test creating valid response."""
        response = BatchEventsResponse(
            received=100,
            enqueued=95,
            dropped=5,
            status="partial",
        )
        assert response.received == 100
        assert response.enqueued == 95
        assert response.dropped == 5
        assert response.status == "partial"

    def test_status_values(self):
        """Test valid status values."""
        for status in ["queued", "partial", "failed"]:
            response = BatchEventsResponse(
                received=10,
                enqueued=10,
                dropped=0,
                status=status,
            )
            assert response.status == status


class TestEventQueryRequest:
    """Tests for EventQueryRequest model."""

    def test_default_values(self):
        """Test default query values."""
        query = EventQueryRequest()
        assert query.limit == 100
        assert query.offset == 0
        assert query.trace_id is None

    def test_filter_by_trace_id(self):
        """Test filtering by trace_id."""
        query = EventQueryRequest(trace_id="4bf92f3577b34da6a3ce929d0e0e4736")
        assert query.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"

    def test_filter_by_actions(self):
        """Test filtering by actions."""
        query = EventQueryRequest(actions=["deny", "warn"])
        assert query.actions == ["deny", "warn"]

    def test_limit_bounds(self):
        """Test limit bounds."""
        with pytest.raises(ValidationError):
            EventQueryRequest(limit=0)  # must be >= 1
        with pytest.raises(ValidationError):
            EventQueryRequest(limit=2000)  # must be <= 1000


class TestControlStats:
    """Tests for ControlStats model."""

    def test_valid_stats(self):
        """Test creating valid stats."""
        stats = ControlStats(
            control_id=123,
            control_name="sql-injection-check",
            execution_count=1000,
            match_count=50,
            non_match_count=950,
            allow_count=950,
            deny_count=45,
            warn_count=5,
            log_count=0,
            error_count=0,
            avg_confidence=0.95,
        )
        assert stats.execution_count == 1000
        assert stats.match_count == 50
        assert stats.non_match_count == 950
        assert stats.deny_count == 45


class TestStatsRequest:
    """Tests for StatsRequest model."""

    def test_valid_request(self):
        """Test creating valid stats request."""
        request = StatsRequest(
            agent_uuid=uuid4(),
            time_range="5m",
        )
        assert request.time_range == "5m"

    def test_time_range_values(self):
        """Test valid time range values."""
        for time_range in ["1m", "5m", "15m", "1h", "24h", "7d", "30d", "180d", "365d"]:
            request = StatsRequest(
                agent_uuid=uuid4(),
                time_range=time_range,
            )
            assert request.time_range == time_range




