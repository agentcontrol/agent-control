"""Tests for the observability module (EventBatcher)."""

import asyncio
import logging
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agent_control_models import ControlExecutionEvent
from agent_control_telemetry import (
    DEFAULT_CONTROL_EVENT_SINK_NAME,
    REGISTERED_CONTROL_EVENT_SINK_NAME,
)
from agent_control_telemetry.sinks import BaseControlEventSink, SinkResult

from agent_control.observability import (
    EventBatcher,
    add_event,
    get_event_batcher,
    get_event_sink,
    get_registered_control_event_sink_factory_names,
    get_registered_control_event_sinks,
    init_observability,
    is_observability_enabled,
    log_span_end,
    log_span_start,
    register_control_event_sink,
    register_control_event_sink_factory,
    shutdown_observability,
    sync_shutdown_observability,
    unregister_control_event_sink,
    write_events,
)
from agent_control.otel_sink import OTEL_CONTROL_EVENT_SINK_NAME
from agent_control.settings import SDKSettings, configure_settings, get_settings
from agent_control_models import ControlExecutionEvent
from agent_control_telemetry import (
    DEFAULT_CONTROL_EVENT_SINK_NAME,
    REGISTERED_CONTROL_EVENT_SINK_NAME,
)
from agent_control_telemetry.sinks import BaseControlEventSink, SinkResult


def create_mock_event():
    """Create a mock ControlExecutionEvent for testing."""
    mock_event = MagicMock()
    mock_event.model_dump = MagicMock(return_value={
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
        "agent_name": "test-agent",
        "control_id": 1,
        "control_name": "test-control",
        "check_stage": "pre",
        "applies_to": "llm_call",
        "action": "observe",
        "matched": False,
        "confidence": 0.95,
        "timestamp": datetime.now(UTC).isoformat(),
    })
    return mock_event


class RecordingSink(BaseControlEventSink):
    """Test sink that records the exact event batches it receives."""

    def __init__(self, *, accepted: int | None = None):
        self.accepted = accepted
        self.received_batches: list[list[ControlExecutionEvent]] = []

    def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        self.received_batches.append(list(events))
        accepted = self.accepted if self.accepted is not None else len(events)
        dropped = max(len(events) - accepted, 0)
        return SinkResult(accepted=accepted, dropped=dropped)


class LifecycleRecordingSink(RecordingSink):
    """Test sink that records shutdown lifecycle hooks."""

    def __init__(self) -> None:
        super().__init__()
        self.flush_calls = 0
        self.close_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class AsyncLifecycleRecordingSink(RecordingSink):
    """Test sink with async shutdown lifecycle hooks."""

    def __init__(self) -> None:
        super().__init__()
        self.flush_calls = 0
        self.close_calls = 0

    async def flush(self) -> None:
        self.flush_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def reset_observability_state() -> None:
    """Clear global observability state between tests."""
    import agent_control.observability as obs

    obs._batcher = None
    obs._event_sink = None
    obs._configured_named_event_sink = None
    obs._configured_named_event_sink_selection = None
    configure_settings(
        observability_enabled=True,
        observability_sink_name=DEFAULT_CONTROL_EVENT_SINK_NAME,
        observability_sink_config={},
        api_key_header="X-API-Key",
    )
    with obs._used_custom_event_sinks_lock:
        obs._used_custom_event_sinks.clear()
    with obs._external_event_sinks_lock:
        obs._external_event_sinks.clear()
    for name in obs.get_registered_control_event_sink_factory_names():
        obs.unregister_control_event_sink_factory(name)
    obs._register_builtin_control_event_sink_factories()


class TestEventBatcherInit:
    """Tests for EventBatcher initialization."""

    def test_init_default_values(self):
        """Test EventBatcher initializes with default values."""
        batcher = EventBatcher()
        assert batcher.api_key_header == get_settings().api_key_header
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
            api_key_header="X-Custom-API-Key",
            batch_size=50,
            flush_interval=5.0,
        )
        assert batcher.server_url == "http://custom:9000"
        assert batcher.api_key == "test-key"
        assert batcher.api_key_header == "X-Custom-API-Key"
        assert batcher.batch_size == 50
        assert batcher.flush_interval == 5.0

    def test_init_from_settings(self):
        """Test EventBatcher reads from settings."""
        from agent_control.settings import configure_settings

        original_settings = get_settings().model_dump()

        try:
            # Configure settings programmatically
            configure_settings(
                url="http://configured-server:8080",
                api_key="configured-api-key",
                api_key_header="X-Custom-API-Key",
            )

            batcher = EventBatcher()
            assert batcher.server_url == "http://configured-server:8080"
            assert batcher.api_key == "configured-api-key"
            assert batcher.api_key_header == "X-Custom-API-Key"
        finally:
            # Restore original settings
            configure_settings(**original_settings)


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

        with patch(
            "agent_control.observability.httpx.Client",
            return_value=client_context,
        ) as client_ctor:
            result = batcher._send_batch_sync([create_mock_event()])

        assert result is True
        client_ctor.assert_called_once_with(timeout=30.0)
        client.post.assert_called_once()
        assert client.post.call_args.kwargs["headers"]["X-API-Key"] == "test-key"

    def test_send_batch_sync_uses_configured_api_key_header(self):
        batcher = EventBatcher(
            server_url="http://test:8000",
            api_key="test-key",
            api_key_header="X-Custom-API-Key",
        )
        response = MagicMock(status_code=202, text="accepted")
        client = MagicMock()
        client.post.return_value = response
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        with patch(
            "agent_control.observability.httpx.Client",
            return_value=client_context,
        ):
            result = batcher._send_batch_sync([create_mock_event()])

        assert result is True
        headers = client.post.call_args.kwargs["headers"]
        assert headers["X-Custom-API-Key"] == "test-key"
        assert "X-API-Key" not in headers

    def test_build_batch_request_uses_settings_api_key_header(self):
        original_settings = get_settings().model_dump()
        try:
            configure_settings(
                api_key="settings-key",
                api_key_header="X-Custom-API-Key",
            )
            batcher = EventBatcher()

            _, headers, _ = batcher._build_batch_request([create_mock_event()])

            assert headers["X-Custom-API-Key"] == "settings-key"
            assert "X-API-Key" not in headers
        finally:
            configure_settings(**original_settings)

    def test_send_batch_sync_returns_false_on_401_without_retry(self):
        batcher = EventBatcher()
        response = MagicMock(status_code=401, text="unauthorized")
        client = MagicMock()
        client.post.return_value = response
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        with patch(
            "agent_control.observability.httpx.Client",
            return_value=client_context,
        ) as client_ctor:
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
        import agent_control.observability as obs

        old_batcher = obs._batcher
        old_sink = obs._event_sink
        old_external_sinks = obs.get_registered_control_event_sinks()
        reset_observability_state()

        try:
            assert get_event_batcher() is None
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink
            for sink in old_external_sinks:
                register_control_event_sink(sink)

    def test_get_event_sink_not_initialized(self):
        """Test get_event_sink returns None when not initialized."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink
        old_external_sinks = obs.get_registered_control_event_sinks()
        reset_observability_state()

        try:
            assert get_event_sink() is None
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink
            for sink in old_external_sinks:
                register_control_event_sink(sink)

    def test_is_observability_enabled_false(self):
        """Test is_observability_enabled returns False when not initialized."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink
        old_external_sinks = obs.get_registered_control_event_sinks()
        reset_observability_state()

        try:
            assert is_observability_enabled() is False
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink
            for sink in old_external_sinks:
                register_control_event_sink(sink)

    def test_add_event_without_batcher(self):
        """Test add_event returns False when batcher not initialized."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink
        old_external_sinks = obs.get_registered_control_event_sinks()
        reset_observability_state()

        try:
            result = add_event(create_mock_event())
            assert result is False
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink
            for sink in old_external_sinks:
                register_control_event_sink(sink)


class TestExternalControlEventSinks:
    """Tests for vendor-neutral external control-event sink registration."""

    def setup_method(self) -> None:
        self._import_and_reset()

    def teardown_method(self) -> None:
        sync_shutdown_observability()
        self._import_and_reset()

    @staticmethod
    def _import_and_reset() -> None:
        reset_observability_state()

    def test_register_and_unregister_external_sink(self):
        sink = RecordingSink()

        register_control_event_sink(sink)
        register_control_event_sink(sink)

        assert get_registered_control_event_sinks() == (sink,)
        assert is_observability_enabled() is False

        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)
        assert is_observability_enabled() is True

        unregister_control_event_sink(sink)

        assert get_registered_control_event_sinks() == ()
        assert is_observability_enabled() is False

    def test_equal_but_distinct_sinks_register_and_unregister_by_identity(self):
        class EqualityAwareSink(RecordingSink):
            def __init__(self, label: str) -> None:
                super().__init__()
                self.label = label

            def __eq__(self, other: object) -> bool:
                return isinstance(other, EqualityAwareSink) and self.label == other.label

        first_sink = EqualityAwareSink("demo")
        second_sink = EqualityAwareSink("demo")

        register_control_event_sink(first_sink)
        register_control_event_sink(second_sink)

        assert get_registered_control_event_sinks() == (first_sink, second_sink)

        unregister_control_event_sink(first_sink)
        assert get_registered_control_event_sinks() == (second_sink,)

        unregister_control_event_sink(second_sink)
        assert get_registered_control_event_sinks() == ()

    def test_registered_sink_does_not_activate_when_observability_disabled(self):
        sink = RecordingSink()
        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)
        configure_settings(observability_enabled=False)

        result = add_event(create_mock_event())

        assert result is False
        assert sink.received_batches == []
        assert is_observability_enabled() is False

    def test_write_events_delivers_to_external_sink_without_builtin_batcher(self):
        sink = RecordingSink()
        event = create_mock_event()

        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        result = add_event(event)

        assert result is True
        assert sink.received_batches == [[event]]
        assert get_event_sink() is None

    def test_default_sink_uses_builtin_even_when_registered_sink_exists(self):
        sink = RecordingSink()
        register_control_event_sink(sink)

        batcher = init_observability(enabled=True)
        assert batcher is not None
        batcher.add_event = MagicMock(return_value=True)
        event = create_mock_event()

        result = add_event(event)

        assert result is True
        batcher.add_event.assert_called_once_with(event)
        assert sink.received_batches == []

    def test_registered_sink_selected_by_config_overrides_builtin_sink(self):
        sink = RecordingSink()
        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        batcher = init_observability(enabled=True)
        assert batcher is None
        event = create_mock_event()

        result = add_event(event)

        assert result is True
        assert sink.received_batches == [[event]]

    def test_registered_sink_failure_does_not_fall_back_to_builtin_sink(self):
        sink = RecordingSink()
        sink.write_events = MagicMock(side_effect=RuntimeError("boom"))
        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        batcher = init_observability(enabled=True)
        assert batcher is None

        result = add_event(create_mock_event())

        assert result is False

    def test_switching_back_to_default_restores_builtin_sink(self):
        sink = RecordingSink()
        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        batcher = init_observability(enabled=True)
        assert batcher is None

        configure_settings(observability_sink_name=DEFAULT_CONTROL_EVENT_SINK_NAME)
        batcher = init_observability(enabled=True)
        assert batcher is not None
        batcher.add_event = MagicMock(return_value=True)

        result = add_event(create_mock_event())

        assert result is True
        batcher.add_event.assert_called_once()

    def test_registered_sink_controls_write_result_when_selected(self):
        sink = RecordingSink(accepted=0)
        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        result = add_event(create_mock_event())

        assert result is False

    def test_registered_sink_write_fails_when_any_fanout_sink_fails(self):
        first_sink = RecordingSink(accepted=0)
        second_sink = RecordingSink(accepted=1)
        register_control_event_sink(first_sink)
        register_control_event_sink(second_sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        result = add_event(create_mock_event())

        assert result is False
        assert len(first_sink.received_batches) == 1
        assert len(second_sink.received_batches) == 1

    def test_registered_sink_write_reports_partial_batch_delivery(self):
        first_sink = RecordingSink(accepted=2)
        second_sink = RecordingSink(accepted=3)
        register_control_event_sink(first_sink)
        register_control_event_sink(second_sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        result = write_events([create_mock_event() for _ in range(3)])

        assert result.accepted == 2
        assert result.dropped == 1

    def test_named_sink_factory_is_selected_by_config(self):
        sink = RecordingSink()
        register_control_event_sink_factory("custom", lambda config: sink)
        configure_settings(observability_sink_name="custom", observability_sink_config={"x": 1})

        result = add_event(create_mock_event())

        assert result is True
        assert sink.received_batches
        assert get_registered_control_event_sink_factory_names() == (
            "custom",
            OTEL_CONTROL_EVENT_SINK_NAME,
        )

    def test_named_sink_factory_failure_disables_delivery_without_raising(self):
        register_control_event_sink_factory(
            "custom",
            lambda config: (_ for _ in ()).throw(RuntimeError(f"boom:{config['x']}")),
        )
        configure_settings(observability_sink_name="custom", observability_sink_config={"x": 1})

        assert is_observability_enabled() is False
        result = add_event(create_mock_event())

        assert result is False

    def test_named_sink_factory_resolution_is_serialized(self):
        sink = RecordingSink()
        resolve_entered = threading.Event()
        resolve_allowed = threading.Event()
        factory_calls = 0
        factory_calls_lock = threading.Lock()
        thread_errors: list[BaseException] = []

        def factory(config: dict[str, object]) -> RecordingSink:
            nonlocal factory_calls
            del config
            with factory_calls_lock:
                factory_calls += 1
            resolve_entered.set()
            resolve_allowed.wait(timeout=1.0)
            return sink

        register_control_event_sink_factory("custom", factory)
        configure_settings(observability_sink_name="custom", observability_sink_config={"x": 1})

        def write_from_thread() -> None:
            try:
                write_events([create_mock_event()])
            except BaseException as exc:  # pragma: no cover - test guard
                thread_errors.append(exc)

        first_thread = threading.Thread(target=write_from_thread)
        second_thread = threading.Thread(target=write_from_thread)

        first_thread.start()
        assert resolve_entered.wait(timeout=1.0)

        second_thread.start()
        time.sleep(0.1)

        with factory_calls_lock:
            assert factory_calls == 1

        resolve_allowed.set()
        first_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)

        assert first_thread.is_alive() is False
        assert second_thread.is_alive() is False
        assert thread_errors == []
        assert sink.received_batches
        assert len(sink.received_batches) == 2

    def test_unknown_named_sink_disables_delivery(self):
        configure_settings(observability_sink_name="missing")

        result = add_event(create_mock_event())

        assert result is False


class TestInitObservability:
    """Tests for init_observability function."""

    def test_init_disabled_when_explicitly_off(self):
        """Test that init_observability returns None when explicitly disabled."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink
        obs._batcher = None
        obs._event_sink = None

        try:
            result = init_observability(enabled=False)
            assert result is None
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink

    def test_enabled_override_updates_global_settings(self):
        """Test that enabled= persists the observability setting."""
        import agent_control.observability as obs

        old_batcher = obs._batcher
        old_sink = obs._event_sink
        original_settings = get_settings().model_dump()
        obs._batcher = None
        obs._event_sink = None

        try:
            configure_settings(observability_enabled=True)

            result = init_observability(enabled=False)

            assert result is None
            assert get_settings().observability_enabled is False
            assert is_observability_enabled() is False
        finally:
            configure_settings(**original_settings)
            obs._batcher = old_batcher
            obs._event_sink = old_sink

    def test_init_enabled_creates_batcher(self):
        """Test that init_observability creates batcher when enabled."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink
        obs._batcher = None
        obs._event_sink = None

        try:
            result = init_observability(
                server_url="http://test:8000",
                api_key="test-key",
                api_key_header="X-Custom-API-Key",
                enabled=True,
            )
            assert result is not None
            assert isinstance(result, EventBatcher)
            assert result.api_key_header == "X-Custom-API-Key"
            assert result._running is True
            assert get_event_sink() is not None

            # Cleanup
            obs.sync_shutdown_observability()
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink

    def test_init_non_default_sink_does_not_create_batcher(self):
        """Test that non-default sink selection skips built-in batcher startup."""
        import agent_control.observability as obs

        old_batcher = obs._batcher
        old_sink = obs._event_sink
        obs._batcher = None
        obs._event_sink = None
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)
        sink = RecordingSink()
        register_control_event_sink(sink)

        try:
            with patch.object(obs.EventBatcher, "start", autospec=True) as start_mock:
                result = init_observability(enabled=True)

            assert result is None
            assert get_event_batcher() is None
            assert get_event_sink() is None
            start_mock.assert_not_called()
        finally:
            unregister_control_event_sink(sink)
            configure_settings(observability_sink_name=DEFAULT_CONTROL_EVENT_SINK_NAME)
            obs._batcher = old_batcher
            obs._event_sink = old_sink

    def test_init_switch_to_non_default_sink_shuts_down_existing_batcher(self):
        """Test that switching away from default tears down the built-in batcher."""
        import agent_control.observability as obs

        old_batcher = obs._batcher
        old_sink = obs._event_sink
        obs._batcher = None
        obs._event_sink = None
        sink = RecordingSink()
        register_control_event_sink(sink)

        try:
            batcher = init_observability(enabled=True)
            assert batcher is not None

            with patch.object(batcher, "shutdown", autospec=True) as shutdown_mock:
                result = init_observability(
                    enabled=True,
                    sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME,
                )

            assert result is None
            shutdown_mock.assert_called_once_with()
            assert get_event_batcher() is None
            assert get_event_sink() is None
        finally:
            unregister_control_event_sink(sink)
            configure_settings(observability_sink_name=DEFAULT_CONTROL_EVENT_SINK_NAME)
            obs._batcher = old_batcher
            obs._event_sink = old_sink

    def test_init_switching_named_sink_without_config_clears_stale_config(self):
        first_sink = RecordingSink()
        second_sink = RecordingSink()
        first_configs: list[dict[str, object]] = []
        second_configs: list[dict[str, object]] = []
        register_control_event_sink_factory(
            "first",
            lambda config: first_configs.append(config) or first_sink,
        )
        register_control_event_sink_factory(
            "second",
            lambda config: second_configs.append(config) or second_sink,
        )

        init_observability(
            enabled=True,
            sink_name="first",
            sink_config={"project": "demo"},
        )
        init_observability(
            enabled=True,
            sink_name="second",
        )

        result = add_event(create_mock_event())

        assert result is True
        assert first_configs == []
        assert second_configs == [{}]
        assert len(second_sink.received_batches) == 1

    def test_init_idempotent(self):
        """Test that init_observability is idempotent."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink
        obs._batcher = None
        obs._event_sink = None

        try:
            batcher1 = init_observability(enabled=True)
            batcher2 = init_observability(enabled=True)

            assert batcher1 is batcher2

            obs.sync_shutdown_observability()
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink


def test_sdk_settings_parse_observability_sink_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_CONTROL_OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("AGENT_CONTROL_OBSERVABILITY_SINK_NAME", "galileo")
    monkeypatch.setenv("AGENT_CONTROL_OBSERVABILITY_SINK_CONFIG", '{"project":"demo"}')

    settings = SDKSettings()

    assert settings.observability_enabled is True
    assert settings.observability_sink_name == "galileo"
    assert settings.observability_sink_config == {"project": "demo"}


def test_sdk_settings_parse_otel_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_CONTROL_OTEL_ENABLED", "true")
    monkeypatch.setenv("AGENT_CONTROL_OTEL_ENDPOINT", "http://collector:4318/v1/traces")
    monkeypatch.setenv("AGENT_CONTROL_OTEL_HEADERS", '{"authorization":"Bearer demo"}')
    monkeypatch.setenv("AGENT_CONTROL_OTEL_SERVICE_NAME", "agent-control-tests")

    settings = SDKSettings()

    assert settings.otel_enabled is True
    assert settings.otel_endpoint == "http://collector:4318/v1/traces"
    assert settings.otel_headers == {"authorization": "Bearer demo"}
    assert settings.otel_service_name == "agent-control-tests"


class TestShutdownObservability:
    """Tests for shutdown_observability function."""

    def setup_method(self) -> None:
        reset_observability_state()

    def teardown_method(self) -> None:
        sync_shutdown_observability()
        reset_observability_state()

    @pytest.mark.asyncio
    async def test_shutdown_flushes_and_stops(self):
        """Test that shutdown flushes remaining events and stops batcher."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink

        try:
            batcher = init_observability(enabled=True)
            batcher._send_batch = AsyncMock(return_value=True)

            # Add some events
            for _ in range(3):
                batcher.add_event(create_mock_event())

            await shutdown_observability()

            # Batcher should be stopped and cleared
            assert obs._batcher is None
            assert obs._event_sink is None
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink

    @pytest.mark.asyncio
    async def test_shutdown_without_batcher(self):
        """Test that shutdown is safe when batcher not initialized."""
        import agent_control.observability as obs
        old_batcher = obs._batcher
        old_sink = obs._event_sink
        obs._batcher = None
        obs._event_sink = None

        try:
            await shutdown_observability()  # Should not raise
        finally:
            obs._batcher = old_batcher
            obs._event_sink = old_sink

    def test_sync_shutdown_preserves_programmatic_sink_selection(self):
        configure_settings(
            observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME,
            observability_sink_config={"project": "demo"},
        )

        sync_shutdown_observability()

        settings = get_settings()
        assert settings.observability_sink_name == REGISTERED_CONTROL_EVENT_SINK_NAME
        assert settings.observability_sink_config == {"project": "demo"}

    def test_sync_shutdown_does_not_replace_programmatic_sink_selection_with_environment(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("AGENT_CONTROL_OBSERVABILITY_SINK_NAME", "galileo")
        monkeypatch.setenv("AGENT_CONTROL_OBSERVABILITY_SINK_CONFIG", '{"project":"demo"}')
        configure_settings(
            observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME,
            observability_sink_config={"project": "override"},
        )

        sync_shutdown_observability()

        settings = get_settings()
        assert settings.observability_sink_name == REGISTERED_CONTROL_EVENT_SINK_NAME
        assert settings.observability_sink_config == {"project": "override"}

    def test_init_without_sink_overrides_preserves_programmatic_sink_settings(self):
        configure_settings(
            observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME,
            observability_sink_config={"project": "demo"},
        )

        batcher = init_observability(enabled=True)

        settings = get_settings()
        assert batcher is None
        assert settings.observability_sink_name == REGISTERED_CONTROL_EVENT_SINK_NAME
        assert settings.observability_sink_config == {"project": "demo"}

    def test_sync_shutdown_does_not_close_registered_custom_sinks(self):
        sync_sink = LifecycleRecordingSink()
        async_sink = AsyncLifecycleRecordingSink()
        register_control_event_sink(sync_sink)
        register_control_event_sink(async_sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)
        assert add_event(create_mock_event()) is True

        sync_shutdown_observability()

        assert sync_sink.flush_calls == 0
        assert sync_sink.close_calls == 0
        assert async_sink.flush_calls == 0
        assert async_sink.close_calls == 0

    def test_sync_shutdown_flushes_and_closes_cached_named_sink(self):
        sink = AsyncLifecycleRecordingSink()
        register_control_event_sink_factory("custom", lambda config: sink)
        configure_settings(observability_sink_name="custom", observability_sink_config={"x": 1})

        assert add_event(create_mock_event()) is True

        sync_shutdown_observability()

        assert sink.flush_calls == 1
        assert sink.close_calls == 1

    def test_switching_named_sink_closes_previous_cached_sink(self):
        first_sink = AsyncLifecycleRecordingSink()
        second_sink = AsyncLifecycleRecordingSink()
        register_control_event_sink_factory("first", lambda config: first_sink)
        register_control_event_sink_factory("second", lambda config: second_sink)
        configure_settings(observability_sink_name="first", observability_sink_config={"x": 1})

        assert add_event(create_mock_event()) is True

        configure_settings(observability_sink_name="second", observability_sink_config={"x": 2})

        assert add_event(create_mock_event()) is True
        assert first_sink.flush_calls == 1
        assert first_sink.close_calls == 1
        assert second_sink.flush_calls == 0
        assert second_sink.close_calls == 0

    def test_sync_shutdown_does_not_close_registered_sinks_after_switching_back_to_default(self):
        sink = AsyncLifecycleRecordingSink()
        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        assert add_event(create_mock_event()) is True

        configure_settings(observability_sink_name=DEFAULT_CONTROL_EVENT_SINK_NAME)
        sync_shutdown_observability()

        assert sink.flush_calls == 0
        assert sink.close_calls == 0

    def test_sync_shutdown_preserves_registered_sink_instances(self):
        sink = AsyncLifecycleRecordingSink()
        register_control_event_sink(sink)
        configure_settings(observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME)

        assert add_event(create_mock_event()) is True

        sync_shutdown_observability()

        assert get_registered_control_event_sinks() == (sink,)


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
        caplog.set_level(logging.INFO)

        # Ensure logging is enabled
        configure_settings(log_enabled=True, log_span_start=True)
        log_span_start("a" * 32, "b" * 16, "test_function", "test-agent")

        # Check that logging occurred
        assert len(caplog.records) >= 1
        assert "Span started" in caplog.records[0].message

    def test_log_span_end(self, caplog):
        """Test log_span_end logs correctly."""
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
            actions={"observe": 1},
        )

        # Check that logging occurred
        assert len(caplog.records) >= 1
        assert "Span completed" in caplog.records[0].message

    def test_log_span_disabled(self, caplog):
        """Test that logging is skipped when span logging is disabled via config."""
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
