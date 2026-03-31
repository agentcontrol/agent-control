"""Tests for the observability module (EventBatcher)."""

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
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
        "agent_name": str(uuid4()),
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
        assert batcher.shutdown_join_timeout == get_settings().shutdown_join_timeout
        assert batcher.shutdown_flush_timeout == get_settings().shutdown_flush_timeout
        assert batcher.shutdown_max_failed_flushes == get_settings().shutdown_max_failed_flushes
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


class TestEventBatcherWorkerThread:
    """Tests for EventBatcher dedicated worker thread."""

    def test_start_creates_worker_thread(self):
        """Test that start() creates a dedicated daemon thread with its own loop."""
        batcher = EventBatcher()
        batcher.start()
        assert batcher._running is True
        assert batcher._thread is not None
        assert batcher._thread.is_alive()
        assert batcher._thread.daemon is True
        assert batcher._loop is not None
        assert not batcher._loop.is_closed()
        batcher.stop()

    def test_sync_repeated_asyncio_run_still_flushes(self):
        """Test that events flush even across repeated asyncio.run() calls.

        Reproduces the sync @control flow: sync_wrapper calls asyncio.run()
        per invocation, creating and closing a caller loop each time. The
        batcher's dedicated thread should be unaffected.
        """
        import time

        batcher = EventBatcher(batch_size=100, flush_interval=0.1)
        batcher._send_batch = AsyncMock(return_value=True)
        batcher.start()

        # Simulate three sync_wrapper-style calls, each with its own asyncio.run()
        for _ in range(3):
            batcher.add_event(create_mock_event())
            # Each sync_wrapper call creates and closes a caller loop
            asyncio.run(asyncio.sleep(0))

        # Wait for the flush interval to fire on the worker thread
        time.sleep(0.3)

        assert batcher._events_sent == 3
        assert len(batcher._events) == 0
        batcher.stop()

    def test_worker_loop_survives_caller_loop_closures(self):
        """Test that worker loop is unaffected by caller loops being closed."""
        batcher = EventBatcher(batch_size=100, flush_interval=0.1)
        batcher._send_batch = AsyncMock(return_value=True)
        batcher.start()

        worker_loop = batcher._loop

        # Create and close several caller loops - should not affect worker
        for _ in range(3):
            loop = asyncio.new_event_loop()
            loop.close()

        assert batcher._loop is worker_loop
        assert not batcher._loop.is_closed()

        batcher.add_event(create_mock_event())
        batcher.add_event(create_mock_event())

        import time
        time.sleep(0.3)

        assert batcher._events_sent == 2
        batcher.stop()

    def test_shutdown_flushes_and_joins_thread(self):
        """Test that shutdown() flushes remaining events and joins the worker thread."""
        batcher = EventBatcher(batch_size=100, flush_interval=60.0)
        batcher._send_batch = AsyncMock(return_value=True)
        batcher.start()

        for _ in range(5):
            batcher.add_event(create_mock_event())

        assert len(batcher._events) == 5

        batcher.shutdown()

        assert batcher._events_sent == 5
        assert len(batcher._events) == 0
        assert not batcher._running
        assert batcher._thread is None

    def test_shutdown_flushes_when_worker_not_running(self):
        """Test that shutdown() still flushes when the worker thread is not running."""
        batcher = EventBatcher(batch_size=100, flush_interval=60.0)

        for _ in range(5):
            batcher.add_event(create_mock_event())

        with patch.object(batcher, "_send_batch_sync", return_value=True):
            batcher.shutdown()

        assert batcher._events_sent == 5
        assert len(batcher._events) == 0
        assert batcher._events_dropped == 0
        assert batcher._thread is None

    def test_shutdown_uses_sync_fallback_when_worker_not_running(self):
        """Shutdown should use the sync fallback path without relying on asyncio."""
        batcher = EventBatcher(batch_size=100, flush_interval=60.0)

        for _ in range(5):
            batcher.add_event(create_mock_event())

        batcher._client = AsyncMock()

        with patch.object(batcher, "_send_batch_sync", return_value=True) as send_batch_sync:
            batcher.shutdown()

        send_batch_sync.assert_called_once()
        assert batcher._events_sent == 5
        assert len(batcher._events) == 0
        # The sync fallback only promises to drop the stale AsyncClient reference.
        assert batcher._client is None

    def test_shutdown_drains_inflight_flush_without_data_loss(self):
        """Test that shutdown waits for in-flight flushes and sends all events."""
        import time

        batcher = EventBatcher(batch_size=100, flush_interval=60.0)

        async def slow_send(events):
            await asyncio.sleep(0.05)
            return True

        batcher._send_batch = slow_send
        batcher.start()

        # Trigger multiple flushes and allow one to start before shutdown.
        for _ in range(350):
            batcher.add_event(create_mock_event())
        time.sleep(0.02)

        batcher.shutdown()

        assert batcher._events_sent == 350
        assert len(batcher._events) == 0
        assert batcher._events_dropped == 0


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

    @pytest.mark.asyncio
    async def test_flush_all_stops_after_failed_flush_limit(self):
        """Test that flush_all exits after configured consecutive flush failures."""
        batcher = EventBatcher(batch_size=2)
        for _ in range(3):
            batcher.add_event(create_mock_event())

        batcher._send_batch = AsyncMock(return_value=False)

        await batcher.flush_all(max_failed_flushes=2)

        assert batcher._send_batch.await_count == 2
        assert len(batcher._events) == 3

    @pytest.mark.asyncio
    async def test_flush_all_rejects_invalid_failed_flush_limit(self):
        """Test that flush_all validates max_failed_flushes."""
        batcher = EventBatcher()
        with pytest.raises(ValueError, match="max_failed_flushes must be >= 1"):
            await batcher.flush_all(max_failed_flushes=0)


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


class TestEventBatcherSendBatchSync:
    """Tests for sync HTTP sending used during shutdown fallback."""

    def test_send_batch_sync_returns_true_on_202(self):
        batcher = EventBatcher(server_url="http://test:8000", api_key="test-key")
        response = MagicMock(status_code=202, text="accepted")
        client = MagicMock()
        client.post.return_value = response
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        with patch("agent_control.observability.httpx.Client", return_value=client_context) as client_ctor:
            result = batcher._send_batch_sync([create_mock_event()])

        assert result is True
        client_ctor.assert_called_once_with(timeout=30.0)
        client.post.assert_called_once()

    def test_send_batch_sync_returns_false_on_401_without_retry(self):
        batcher = EventBatcher()
        response = MagicMock(status_code=401, text="unauthorized")
        client = MagicMock()
        client.post.return_value = response
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        with patch("agent_control.observability.httpx.Client", return_value=client_context) as client_ctor:
            result = batcher._send_batch_sync([create_mock_event()])

        assert result is False
        assert client_ctor.call_count == 1
        client.post.assert_called_once()

    def test_send_batch_sync_retries_after_server_error_then_succeeds(self):
        from agent_control.settings import configure_settings

        original = get_settings().model_dump()
        configure_settings(max_retries=2, retry_delay=0.25)
        batcher = EventBatcher()

        first = MagicMock(status_code=500, text="server error")
        second = MagicMock(status_code=202, text="accepted")
        client = MagicMock()
        client.post.side_effect = [first, second]
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        try:
            with (
                patch(
                    "agent_control.observability.httpx.Client",
                    return_value=client_context,
                ) as client_ctor,
                patch("agent_control.observability.time.sleep") as sleep_mock,
            ):
                result = batcher._send_batch_sync([create_mock_event()])

            assert result is True
            assert client_ctor.call_count == 2
            sleep_mock.assert_called_once_with(0.25)
        finally:
            configure_settings(**original)

    def test_send_batch_sync_returns_false_when_deadline_already_expired(self):
        batcher = EventBatcher()

        with (
            patch("agent_control.observability.httpx.Client") as client_ctor,
            patch("agent_control.observability.time.monotonic", return_value=2.0),
        ):
            result = batcher._send_batch_sync([create_mock_event()], deadline=1.0)

        assert result is False
        client_ctor.assert_not_called()

    def test_send_batch_sync_returns_false_when_retry_backoff_exceeds_deadline(self):
        from agent_control.settings import configure_settings

        original = get_settings().model_dump()
        configure_settings(max_retries=3, retry_delay=0.25)
        batcher = EventBatcher()

        client = MagicMock()
        client.post.side_effect = httpx.ConnectError("boom")
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        try:
            with (
                patch(
                    "agent_control.observability.httpx.Client",
                    return_value=client_context,
                ) as client_ctor,
                patch(
                    "agent_control.observability.time.monotonic",
                    side_effect=[0.0, 1.1],
                ),
                patch("agent_control.observability.time.sleep") as sleep_mock,
            ):
                result = batcher._send_batch_sync([create_mock_event()], deadline=1.0)

            assert result is False
            assert client_ctor.call_count == 1
            sleep_mock.assert_not_called()
        finally:
            configure_settings(**original)

    def test_send_batch_sync_handles_timeout_exception(self):
        from agent_control.settings import configure_settings

        original = get_settings().model_dump()
        configure_settings(max_retries=1)
        batcher = EventBatcher()

        client = MagicMock()
        client.post.side_effect = httpx.TimeoutException("boom")
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        try:
            with patch("agent_control.observability.httpx.Client", return_value=client_context):
                result = batcher._send_batch_sync([create_mock_event()])

            assert result is False
        finally:
            configure_settings(**original)

    def test_send_batch_sync_handles_unexpected_exception(self):
        from agent_control.settings import configure_settings

        original = get_settings().model_dump()
        configure_settings(max_retries=1)
        batcher = EventBatcher()

        client = MagicMock()
        client.post.side_effect = RuntimeError("boom")
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        try:
            with patch("agent_control.observability.httpx.Client", return_value=client_context):
                result = batcher._send_batch_sync([create_mock_event()])

            assert result is False
        finally:
            configure_settings(**original)


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

    def test_init_disabled_when_explicitly_off(self):
        """Test that init_observability returns None when explicitly disabled."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        obs._batcher = None

        try:
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


class TestEventBatcherShutdownConfig:
    """Tests for shutdown timeout configuration."""

    def test_shutdown_uses_settings_timeouts(self):
        """Test that shutdown uses configurable join/flush timeouts."""
        from agent_control.settings import configure_settings

        original = get_settings().model_dump()
        configure_settings(shutdown_join_timeout=6.5, shutdown_flush_timeout=4.5)
        batcher = EventBatcher()

        try:
            with (
                patch.object(batcher, "_stop_worker", return_value=True) as stop_worker,
                patch.object(batcher, "_flush_all_without_worker") as fallback_flush,
            ):
                # Force fallback path without invoking real network/client cleanup.
                batcher._events = [create_mock_event()]
                batcher.shutdown()

                stop_worker.assert_called_once_with(graceful=True, join_timeout=6.5)
                fallback_flush.assert_called_once_with(timeout=4.5)
        finally:
            configure_settings(**original)

    def test_sync_shutdown_flush_stops_after_failed_flush_limit(self):
        """Test that sync shutdown fallback exits after configured failed flushes."""
        batcher = EventBatcher(batch_size=2)
        batcher.shutdown_max_failed_flushes = 2
        batcher._client = AsyncMock()
        for _ in range(3):
            batcher.add_event(create_mock_event())

        with patch.object(batcher, "_send_batch_sync", return_value=False) as send_batch_sync:
            batcher._flush_all_without_worker(timeout=1.0)

        assert send_batch_sync.call_count == 2
        assert len(batcher._events) == 3
        assert batcher._client is None

    def test_sync_shutdown_flush_honors_timeout_before_first_attempt(self):
        """Test that sync shutdown fallback exits if its timeout is already exhausted."""
        batcher = EventBatcher()
        batcher._client = AsyncMock()
        batcher.add_event(create_mock_event())

        with (
            patch.object(batcher, "_send_batch_sync") as send_batch_sync,
            patch(
                "agent_control.observability.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
        ):
            batcher._flush_all_without_worker(timeout=0.0)

        send_batch_sync.assert_not_called()
        assert len(batcher._events) == 1
        assert batcher._client is None


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
