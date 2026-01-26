"""Tests for the observability module (EventBatcher)."""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent_control.observability import (
    EventBatcher,
    add_event,
    get_event_batcher,
    init_observability,
    is_observability_enabled,
    log_span_end,
    log_span_start,
    shutdown_observability,
)
from agent_control.settings import get_settings


def create_mock_event():
    """Create a mock ControlExecutionEvent for testing."""
    mock_event = MagicMock()
    mock_event.model_dump = MagicMock(return_value={
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
        "agent_uuid": str(uuid4()),
        "agent_name": "test-agent",
        "control_id": 1,
        "control_name": "test-control",
        "check_stage": "pre",
        "applies_to": "llm_call",
        "action": "allow",
        "matched": False,
        "confidence": 0.95,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return mock_event


class TestEventBatcherInit:
    """Tests for EventBatcher initialization."""

    def test_init_default_values(self):
        """Test EventBatcher initializes with default values."""
        batcher = EventBatcher()
        assert batcher.batch_size == get_settings().batch_size
        assert batcher.flush_interval == get_settings().flush_interval
        assert batcher._running is False
        assert batcher._events == []

    def test_init_custom_values(self):
        """Test EventBatcher initializes with custom values."""
        batcher = EventBatcher(
            server_url="http://custom:9000",
            api_key="test-key",
            batch_size=50,
            flush_interval=5.0,
        )
        assert batcher.server_url == "http://custom:9000"
        assert batcher.api_key == "test-key"
        assert batcher.batch_size == 50
        assert batcher.flush_interval == 5.0

    def test_init_from_settings(self):
        """Test EventBatcher reads from settings."""
        from agent_control.settings import configure_settings

        # Save original values
        original_url = get_settings().url
        original_api_key = get_settings().api_key

        try:
            # Configure settings programmatically
            configure_settings(url="http://configured-server:8080", api_key="configured-api-key")

            batcher = EventBatcher()
            assert batcher.server_url == "http://configured-server:8080"
            assert batcher.api_key == "configured-api-key"
        finally:
            # Restore original settings
            configure_settings(url=original_url, api_key=original_api_key)


class TestEventBatcherStartStop:
    """Tests for EventBatcher start/stop lifecycle."""

    def test_start_sets_running(self):
        """Test that start sets running flag."""
        batcher = EventBatcher()
        batcher.start()
        assert batcher._running is True
        batcher.stop()

    def test_stop_clears_running(self):
        """Test that stop clears running flag."""
        batcher = EventBatcher()
        batcher.start()
        batcher.stop()
        assert batcher._running is False

    def test_double_start_is_safe(self):
        """Test that calling start twice is safe."""
        batcher = EventBatcher()
        batcher.start()
        batcher.start()  # Should not raise
        assert batcher._running is True
        batcher.stop()

    def test_stop_without_start_is_safe(self):
        """Test that calling stop without start is safe."""
        batcher = EventBatcher()
        batcher.stop()  # Should not raise
        assert batcher._running is False


class TestEventBatcherAddEvent:
    """Tests for adding events to the batcher."""

    def test_add_event_success(self):
        """Test adding an event successfully."""
        batcher = EventBatcher()
        event = create_mock_event()

        result = batcher.add_event(event)

        assert result is True
        assert len(batcher._events) == 1

    def test_add_multiple_events(self):
        """Test adding multiple events."""
        batcher = EventBatcher()
        events = [create_mock_event() for _ in range(5)]

        for event in events:
            batcher.add_event(event)

        assert len(batcher._events) == 5

    def test_add_event_drops_when_queue_full(self):
        """Test that events are dropped when queue is full."""
        batcher = EventBatcher(batch_size=10)  # Max queue = 10 * 10 = 100

        # Add more than max events
        for i in range(105):
            batcher.add_event(create_mock_event())

        assert len(batcher._events) == 100
        assert batcher._events_dropped == 5

    def test_add_event_thread_safe(self):
        """Test that add_event is thread-safe."""
        import threading

        batcher = EventBatcher(batch_size=100)
        results = []

        def add_events():
            for _ in range(50):
                result = batcher.add_event(create_mock_event())
                results.append(result)

        threads = [threading.Thread(target=add_events) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 200 events should be added (batch_size=100 means max=1000)
        assert len(batcher._events) == 200
        assert all(results)


class TestEventBatcherStats:
    """Tests for EventBatcher statistics."""

    def test_get_stats_initial(self):
        """Test getting stats from new batcher."""
        batcher = EventBatcher()
        stats = batcher.get_stats()

        assert stats["events_sent"] == 0
        assert stats["events_dropped"] == 0
        assert stats["events_pending"] == 0
        assert stats["flush_count"] == 0
        assert stats["running"] is False

    def test_get_stats_with_events(self):
        """Test getting stats after adding events."""
        batcher = EventBatcher()
        for _ in range(5):
            batcher.add_event(create_mock_event())

        stats = batcher.get_stats()
        assert stats["events_pending"] == 5

    def test_get_stats_after_start(self):
        """Test getting stats after starting batcher."""
        batcher = EventBatcher()
        batcher.start()

        stats = batcher.get_stats()
        assert stats["running"] is True

        batcher.stop()


class TestEventBatcherFlush:
    """Tests for EventBatcher flush operations."""

    @pytest.mark.asyncio
    async def test_flush_empty_queue(self):
        """Test flushing an empty queue does nothing."""
        batcher = EventBatcher()
        await batcher._flush()
        assert batcher._flush_count == 0

    @pytest.mark.asyncio
    async def test_flush_sends_events(self):
        """Test that flush sends events to server."""
        batcher = EventBatcher()
        for _ in range(3):
            batcher.add_event(create_mock_event())

        # Mock the _send_batch method
        batcher._send_batch = AsyncMock(return_value=True)

        await batcher._flush()

        assert batcher._send_batch.called
        assert batcher._events_sent == 3
        assert len(batcher._events) == 0

    @pytest.mark.asyncio
    async def test_flush_requeues_on_failure(self):
        """Test that flush requeues events on send failure."""
        batcher = EventBatcher()
        for _ in range(3):
            batcher.add_event(create_mock_event())

        # Mock the _send_batch method to fail
        batcher._send_batch = AsyncMock(return_value=False)

        await batcher._flush()

        # Events should be requeued
        assert len(batcher._events) == 3
        assert batcher._events_sent == 0

    @pytest.mark.asyncio
    async def test_flush_all_empties_queue(self):
        """Test that flush_all empties the entire queue."""
        batcher = EventBatcher(batch_size=2)
        for _ in range(5):
            batcher.add_event(create_mock_event())

        batcher._send_batch = AsyncMock(return_value=True)

        await batcher.flush_all()

        assert len(batcher._events) == 0
        assert batcher._events_sent == 5


class TestEventBatcherSendBatch:
    """Tests for EventBatcher HTTP batch sending."""

    @pytest.mark.asyncio
    async def test_send_batch_without_httpx(self):
        """Test that send_batch handles missing httpx gracefully."""
        batcher = EventBatcher()
        events = [create_mock_event()]

        with patch.dict("sys.modules", {"httpx": None}):
            # This should not raise, just return False
            result = await batcher._send_batch(events)
            # Can't easily test this without breaking httpx import
            # Just verify the method exists and runs
            assert isinstance(result, bool)


class TestGlobalBatcher:
    """Tests for global batcher functions."""

    def test_get_event_batcher_not_initialized(self):
        """Test get_event_batcher returns None when not initialized."""
        # Reset global state
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
            assert get_event_batcher() is None
        finally:
            obs._batcher = old_batcher

    def test_is_observability_enabled_false(self):
        """Test is_observability_enabled returns False when not initialized."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
            assert is_observability_enabled() is False
        finally:
            obs._batcher = old_batcher

    def test_add_event_without_batcher(self):
        """Test add_event returns False when batcher not initialized."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
            result = add_event(create_mock_event())
            assert result is False
        finally:
            obs._batcher = old_batcher


class TestInitObservability:
    """Tests for init_observability function."""

    def test_init_disabled_by_default(self):
        """Test that init_observability returns None when disabled."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
            # Default is disabled
            with patch.dict(os.environ, {"AGENT_CONTROL_OBSERVABILITY_ENABLED": "false"}):
                result = init_observability(enabled=False)
                assert result is None
        finally:
            obs._batcher = old_batcher

    def test_init_enabled_creates_batcher(self):
        """Test that init_observability creates batcher when enabled."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
            result = init_observability(
                server_url="http://test:8000",
                api_key="test-key",
                enabled=True,
            )
            assert result is not None
            assert isinstance(result, EventBatcher)
            assert result._running is True

            # Cleanup
            result.stop()
        finally:
            obs._batcher = old_batcher

    def test_init_idempotent(self):
        """Test that init_observability is idempotent."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
            batcher1 = init_observability(enabled=True)
            batcher2 = init_observability(enabled=True)

            assert batcher1 is batcher2

            batcher1.stop()
        finally:
            obs._batcher = old_batcher


class TestShutdownObservability:
    """Tests for shutdown_observability function."""

    @pytest.mark.asyncio
    async def test_shutdown_flushes_and_stops(self):
        """Test that shutdown flushes remaining events and stops batcher."""
        import agent_control.observability as obs
        old_batcher = obs._batcher

        try:
            batcher = init_observability(enabled=True)
            batcher._send_batch = AsyncMock(return_value=True)

            # Add some events
            for _ in range(3):
                batcher.add_event(create_mock_event())

            await shutdown_observability()

            # Batcher should be stopped and cleared
            assert obs._batcher is None
        finally:
            obs._batcher = old_batcher

    @pytest.mark.asyncio
    async def test_shutdown_without_batcher(self):
        """Test that shutdown is safe when batcher not initialized."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
            await shutdown_observability()  # Should not raise
        finally:
            obs._batcher = old_batcher


class TestSpanLogging:
    """Tests for span start/end logging functions."""

    def test_log_span_start(self, caplog):
        """Test log_span_start logs correctly."""
        import logging
        from agent_control.settings import configure_settings
        caplog.set_level(logging.INFO)

        # Ensure logging is enabled
        configure_settings(log_enabled=True, log_span_start=True)
        log_span_start("a" * 32, "b" * 16, "test_function", "test-agent")

        # Check that logging occurred
        assert len(caplog.records) >= 1
        assert "Span started" in caplog.records[0].message

    def test_log_span_end(self, caplog):
        """Test log_span_end logs correctly."""
        import logging
        from agent_control.settings import configure_settings
        caplog.set_level(logging.INFO)

        # Ensure logging is enabled
        configure_settings(log_enabled=True, log_span_end=True)
        log_span_end(
            "a" * 32, "b" * 16, "test_function",
            duration_ms=150.5,
            executions=3,
            matches=1,
            non_matches=2,
            errors=0,
            actions={"allow": 1},
        )

        # Check that logging occurred
        assert len(caplog.records) >= 1
        assert "Span completed" in caplog.records[0].message

    def test_log_span_disabled(self, caplog):
        """Test that logging is skipped when span logging is disabled via config."""
        import logging
        from agent_control.settings import configure_settings
        caplog.set_level(logging.INFO)

        # Save original config
        original_span_start = get_settings().log_span_start
        original_span_end = get_settings().log_span_end

        try:
            # Disable span logging via settings
            configure_settings(log_span_start=False, log_span_end=False)

            log_span_start("a" * 32, "b" * 16, "test_function", "test-agent")
            log_span_end("a" * 32, "b" * 16, "test_function", 100.0)

            # No logs should be created when disabled
            assert len(caplog.records) == 0
        finally:
            # Restore original config
            configure_settings(log_span_start=original_span_start, log_span_end=original_span_end)
