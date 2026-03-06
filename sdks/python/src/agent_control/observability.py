"""
Event batching and transmission for Agent Control observability.

This module provides:
1. EventBatcher for collecting and sending control execution events to the server
2. Standard library-compliant logging setup for the SDK

Logging:
    The SDK follows Python logging best practices:
    - Uses hierarchical logger names (agent_control.*)
    - Adds only NullHandler (no formatters or handlers)
    - Applications control log configuration via logging.basicConfig() or handlers

    Example - Configure logging in your application:
        import logging
        logging.basicConfig(level=logging.INFO)
        logging.getLogger('agent_control').setLevel(logging.DEBUG)

Event Batching Usage:
    from agent_control.observability import get_event_batcher, add_event

    # Add an event (usually done automatically by @control decorator)
    add_event(event)

    # On shutdown, flush remaining events
    await shutdown_observability()

Configuration (Environment Variables):
    # Observability (event batching)
    AGENT_CONTROL_OBSERVABILITY_ENABLED: Enable observability (default: true)
    AGENT_CONTROL_BATCH_SIZE: Max events per batch (default: 100)
    AGENT_CONTROL_FLUSH_INTERVAL: Seconds between flushes (default: 5.0)
    AGENT_CONTROL_SHUTDOWN_JOIN_TIMEOUT: Seconds to wait for worker shutdown (default: 5.0)
    AGENT_CONTROL_SHUTDOWN_FLUSH_TIMEOUT: Seconds to wait for fallback flush (default: 5.0)
    AGENT_CONTROL_SHUTDOWN_MAX_FAILED_FLUSHES: Consecutive failed flushes before stop (default: 1)

    # SDK Logging Behavior (what logs to emit)
    AGENT_CONTROL_LOG_ENABLED: Master switch for SDK logging (default: true)
    AGENT_CONTROL_LOG_LEVEL: Kept for backwards compat; use logging.setLevel() instead
    AGENT_CONTROL_LOG_SPAN_START: Emit span start logs (default: true)
    AGENT_CONTROL_LOG_SPAN_END: Emit span end logs (default: true)
    AGENT_CONTROL_LOG_CONTROL_EVAL: Emit per-control evaluation logs (default: true)
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from agent_control.settings import configure_settings, get_settings

if TYPE_CHECKING:
    from agent_control_models import ControlExecutionEvent

# =============================================================================
# Logger Setup - Standard Library Pattern
# =============================================================================
#
# Following Python logging best practices for libraries:
# - Use hierarchical logger names (agent_control.*)
# - Add only NullHandler to suppress "No handler" warnings
# - Let applications configure handlers, formatters, and levels
# - Provide behavioral settings to control what the SDK logs
#
# Applications should configure agent_control loggers like this:
#   import logging
#   logging.basicConfig(level=logging.INFO)
#   logging.getLogger('agent_control').setLevel(logging.DEBUG)

_ROOT_LOGGER_NAME = "agent_control"


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module under the agent_control namespace.

    This follows standard library conventions - applications control logging
    configuration (handlers, formatters, levels), while the SDK just creates
    properly namespaced loggers.

    Args:
        name: Module name (typically __name__)

    Returns:
        Logger instance under agent_control namespace

    Example:
        logger = get_logger(__name__)
        logger.info("Processing started")
    """
    if not name.startswith(_ROOT_LOGGER_NAME):
        name = f"{_ROOT_LOGGER_NAME}.{name}"
    return logging.getLogger(name)


# Add NullHandler to root logger following standard library pattern
# This suppresses "No handlers could be found" warnings while allowing
# applications to configure logging as needed
logging.getLogger(_ROOT_LOGGER_NAME).addHandler(logging.NullHandler())

# Module logger
logger = get_logger(__name__)

# =============================================================================
# Logging Configuration (backwards-compatible wrapper around settings)
# =============================================================================


@dataclass
class LogConfig:
    """
    Configuration for SDK logging behavior.

    This class provides backwards compatibility with the original API.
    Settings are stored in the centralized SDKSettings instance.

    Applications should configure log levels via Python's standard logging
    module (e.g., logging.getLogger('agent_control').setLevel(logging.DEBUG)).
    The fields in this class control which categories of logs the SDK emits.
    """

    enabled: bool = field(default_factory=lambda: get_settings().log_enabled)
    span_start: bool = field(default_factory=lambda: get_settings().log_span_start)
    span_end: bool = field(default_factory=lambda: get_settings().log_span_end)
    control_eval: bool = field(default_factory=lambda: get_settings().log_control_eval)

    @classmethod
    def from_env(cls) -> LogConfig:
        """Load configuration from environment variables (via settings)."""
        return cls(
            enabled=get_settings().log_enabled,
            span_start=get_settings().log_span_start,
            span_end=get_settings().log_span_end,
            control_eval=get_settings().log_control_eval,
        )

    def update(self, config_dict: dict[str, Any]) -> None:
        """Update configuration from a dictionary."""
        # Map old names to new setting names
        mapping = {
            "enabled": "log_enabled",
            "span_start": "log_span_start",
            "span_end": "log_span_end",
            "control_eval": "log_control_eval",
        }
        updates = {}
        for old_key, new_key in mapping.items():
            if old_key in config_dict:
                value = bool(config_dict[old_key])
                updates[new_key] = value
                setattr(self, old_key, value)

        if updates:
            configure_settings(**updates)


# Global logging configuration (for backwards compatibility)
_log_config = LogConfig.from_env()


def configure_logging(config: dict[str, Any] | None = None) -> LogConfig:
    """
    Configure SDK logging behavior (which categories of logs to emit).

    This controls which types of logs the SDK emits, not where they go or
    what level they're logged at. For log level/handler configuration, use
    Python's standard logging module.

    Can be called programmatically to override environment variable defaults.

    Args:
        config: Dictionary with logging options:
            - enabled: bool - Master switch for all SDK logging (default: True)
            - level: str - Kept for backwards compatibility; use logging.setLevel() instead
            - span_start: bool - Emit span start logs (default: True)
            - span_end: bool - Emit span end logs (default: True)
            - control_eval: bool - Emit per-control evaluation logs (default: True)

    Returns:
        Current LogConfig after applying changes

    Example:
        # Control which SDK logs are emitted
        configure_logging({
            "enabled": True,
            "control_eval": False,  # Don't emit per-control logs
        })

        # For log levels, use standard Python logging
        import logging
        logging.getLogger('agent_control').setLevel(logging.DEBUG)
    """
    global _log_config
    if config:
        _log_config.update(config)
    return _log_config


def get_log_config() -> LogConfig:
    """Get the current logging configuration."""
    return _log_config


def _should_log(log_type: str) -> bool:
    """
    Check if a specific log type should be emitted by the SDK.

    This controls which categories of logs the SDK emits, independent of
    Python's logging level filtering. Applications control actual log levels
    via logging.getLogger('agent_control').setLevel().

    Args:
        log_type: Type of log ("span_start", "span_end", "control_eval")

    Returns:
        True if this type of log should be emitted
    """
    if not get_settings().log_enabled:
        return False

    if log_type == "span_start":
        return get_settings().log_span_start
    elif log_type == "span_end":
        return get_settings().log_span_end
    elif log_type == "control_eval":
        return get_settings().log_control_eval

    return True


# =============================================================================
# Event Batching Configuration (now via settings)
# =============================================================================


class EventBatcher:
    """
    Batches control execution events and sends them to the server.

    Events are batched by either:
    - Reaching batch_size events (default: 100)
    - Flush interval timeout (default: 5 seconds)

    Uses a dedicated daemon thread with its own event loop for flush
    scheduling, so it works consistently regardless of caller loop
    lifecycle (sync callers, repeated asyncio.run(), long-lived async
    servers, etc.).

    Thread-safe. add_event() is non-blocking and can be called from
    any thread or async context.

    Attributes:
        server_url: Base URL of the Agent Control server
        api_key: API key for authentication
        batch_size: Maximum events per batch
        flush_interval: Seconds between automatic flushes
    """

    def __init__(
        self,
        server_url: str | None = None,
        api_key: str | None = None,
        batch_size: int | None = None,
        flush_interval: float | None = None,
    ):
        """
        Initialize the EventBatcher.

        Args:
            server_url: Server URL (defaults to get_settings().url)
            api_key: API key (defaults to get_settings().api_key)
            batch_size: Max events per batch (defaults to get_settings().batch_size)
            flush_interval: Seconds between flushes (defaults to get_settings().flush_interval)
        """
        self.server_url = server_url or get_settings().url
        self.api_key = api_key or get_settings().api_key
        self.batch_size = batch_size if batch_size is not None else get_settings().batch_size
        if flush_interval is not None:
            self.flush_interval = flush_interval
        else:
            self.flush_interval = get_settings().flush_interval
        self.shutdown_join_timeout = get_settings().shutdown_join_timeout
        self.shutdown_flush_timeout = get_settings().shutdown_flush_timeout
        self.shutdown_max_failed_flushes = get_settings().shutdown_max_failed_flushes

        # Thread-safe event storage
        self._events: list[ControlExecutionEvent] = []
        self._lock = threading.Lock()

        # Dedicated worker loop and thread
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._flush_signal: asyncio.Event | None = None
        self._worker_ready = threading.Event()
        self._graceful_shutdown = False
        self._running = False

        # Reusable HTTP client for connection pooling
        self._client: httpx.AsyncClient | None = None

        # Stats
        self._events_sent = 0
        self._events_dropped = 0
        self._flush_count = 0

    def start(self) -> None:
        """Start the dedicated worker thread and flush loop."""
        if self._running:
            return

        self._running = True
        self._graceful_shutdown = False
        self._worker_ready.clear()
        self._thread = threading.Thread(
            target=self._run_worker_loop,
            name="agent-control-event-batcher",
            daemon=True,
        )
        self._thread.start()
        if not self._worker_ready.wait(timeout=1.0):
            logger.warning("EventBatcher worker thread did not signal readiness in time")
        logger.debug("EventBatcher started (dedicated worker thread)")

    def _run_worker_loop(self) -> None:
        """Entry point for the worker thread. Runs the event loop."""
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._flush_signal = asyncio.Event()
        self._worker_ready.set()
        try:
            loop.run_until_complete(self._flush_loop())
        except RuntimeError:
            # Can happen if emergency stop is requested while loop is running
            pass
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except RuntimeError:
                pass
            loop.close()
            self._flush_signal = None
            self._loop = None
            self._worker_ready.clear()

    def _signal_flush(self) -> None:
        """Wake the worker loop to perform (or finish) a flush cycle."""
        loop = self._loop
        signal = self._flush_signal
        if loop is None or signal is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(signal.set)
        except RuntimeError:
            # Expected during shutdown races: worker teardown can close/swap
            # loop state between our check and call_soon_threadsafe().
            pass

    def _stop_worker(self, *, graceful: bool, join_timeout: float) -> bool:
        """Stop the worker thread and return whether it fully stopped."""
        self._graceful_shutdown = graceful
        self._running = False
        self._signal_flush()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)

        if self._thread and self._thread.is_alive():
            # Emergency fallback if worker is still hung.
            loop = self._loop
            if loop and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except RuntimeError:
                    pass
            self._thread.join(timeout=1.0)

        thread_alive = self._thread.is_alive() if self._thread else False
        if thread_alive:
            logger.warning("EventBatcher worker thread did not stop cleanly")
            return False
        self._thread = None
        return True

    def _flush_all_without_worker(self, *, timeout: float) -> None:
        """Flush remaining events in a helper thread when no worker loop is available."""
        flush_error: Exception | None = None

        def run_flush() -> None:
            nonlocal flush_error
            try:
                asyncio.run(self.flush_all())
            except Exception as e:
                flush_error = e

        helper_thread = threading.Thread(
            target=run_flush,
            name="agent-control-event-batcher-shutdown-flush",
            daemon=True,
        )
        helper_thread.start()
        helper_thread.join(timeout=timeout)
        if helper_thread.is_alive():
            logger.warning("Fallback shutdown flush timed out after %.1f seconds", timeout)
            return
        if flush_error is not None:
            logger.error("Error during fallback shutdown flush: %s", flush_error)

    def stop(self) -> None:
        """Stop the worker thread. Does not flush remaining events."""
        self._stop_worker(graceful=False, join_timeout=2.0)
        logger.debug("EventBatcher stopped")

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def add_event(self, event: ControlExecutionEvent) -> bool:
        """
        Add an event to the batch.

        Thread-safe and non-blocking. Can be called from any thread or
        async context.

        Args:
            event: Control execution event to add

        Returns:
            True if event was added, False if dropped (e.g., queue full)
        """
        should_flush = False
        with self._lock:
            if len(self._events) >= self.batch_size * 10:
                self._events_dropped += 1
                logger.warning("Event dropped: queue full")
                return False

            self._events.append(event)
            should_flush = len(self._events) >= self.batch_size

        if should_flush:
            self._schedule_flush()

        return True

    def _schedule_flush(self) -> None:
        """Schedule an immediate flush on the worker loop (non-blocking)."""
        if not self._running:
            return
        self._signal_flush()

    async def _flush_loop(self) -> None:
        """Background task that flushes events periodically."""
        signal = self._flush_signal
        if signal is None:
            logger.error("Flush loop started without a worker flush signal")
            return

        while self._running:
            try:
                await asyncio.wait_for(signal.wait(), timeout=self.flush_interval)
                signal.clear()
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Flush loop wakeup error: {e}")
                continue

            if not self._running:
                break

            try:
                await self._flush()
            except Exception as e:
                logger.error(f"Flush loop error: {e}")

        try:
            if self._graceful_shutdown:
                await self.flush_all(
                    close_client=False,
                    max_failed_flushes=self.shutdown_max_failed_flushes,
                )
        except Exception as e:
            logger.error(f"Error during flush loop shutdown: {e}")
        finally:
            try:
                await self.close()
            except Exception as e:
                logger.error(f"Error closing observability client: {e}")

    async def _flush(self) -> bool:
        """Flush current batch to server."""
        with self._lock:
            if not self._events:
                return True
            events_to_send = self._events[:self.batch_size]
            self._events = self._events[self.batch_size:]

        if not events_to_send:
            return True

        success = await self._send_batch(events_to_send)

        if success:
            with self._lock:
                self._events_sent += len(events_to_send)
                self._flush_count += 1
                total_sent = self._events_sent
            logger.debug(
                f"Flushed {len(events_to_send)} events "
                f"(total sent: {total_sent})"
            )
            return True
        else:
            with self._lock:
                self._events = events_to_send + self._events
            logger.warning(f"Failed to send batch, re-queued {len(events_to_send)} events")
            return False

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client for connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _send_batch(self, events: list[ControlExecutionEvent]) -> bool:
        """
        Send a batch of events to the server.

        Args:
            events: List of events to send

        Returns:
            True if sent successfully, False otherwise
        """
        url = f"{self.server_url}/api/v1/observability/events"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        payload = {
            "events": [event.model_dump(mode="json") for event in events]
        }

        client = await self._get_client()

        for attempt in range(get_settings().max_retries):
            try:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 202:
                    return True
                elif response.status_code == 401:
                    logger.error("Authentication failed - check API key")
                    return False
                else:
                    logger.warning(
                        f"Server returned {response.status_code}: {response.text}"
                    )

            except httpx.TimeoutException:
                logger.warning(f"Timeout sending events (attempt {attempt + 1})")
            except httpx.ConnectError:
                logger.warning(f"Connection error (attempt {attempt + 1})")
            except Exception as e:
                logger.error(f"Error sending events: {e}")

            if attempt < get_settings().max_retries - 1:
                await asyncio.sleep(get_settings().retry_delay * (attempt + 1))

        return False

    async def flush_all(
        self,
        *,
        close_client: bool = True,
        max_failed_flushes: int | None = None,
    ) -> None:
        """
        Flush all remaining events.

        Stops retrying after max_failed_flushes consecutive flush failures to
        avoid infinite shutdown loops when the server is unavailable.
        """
        failure_limit = (
            max_failed_flushes
            if max_failed_flushes is not None
            else self.shutdown_max_failed_flushes
        )
        if failure_limit < 1:
            raise ValueError("max_failed_flushes must be >= 1")
        consecutive_failures = 0

        while True:
            with self._lock:
                if not self._events:
                    break

            flushed = await self._flush()
            if flushed:
                consecutive_failures = 0
                continue

            consecutive_failures += 1
            if consecutive_failures >= failure_limit:
                with self._lock:
                    pending = len(self._events)
                logger.warning(
                    "Stopping flush_all after %d consecutive failed flushes; %d event(s) pending",
                    consecutive_failures,
                    pending,
                )
                break

        if close_client:
            await self.close()

    def shutdown(self) -> None:
        """
        Synchronous shutdown - flush remaining events and join worker thread.

        Called on process exit via atexit.
        """
        with self._lock:
            initial_remaining = len(self._events)
        if initial_remaining > 0:
            logger.info(f"Flushing {initial_remaining} remaining events on shutdown...")

        worker_stopped = self._stop_worker(
            graceful=True,
            join_timeout=self.shutdown_join_timeout,
        )

        with self._lock:
            needs_fallback_flush = bool(self._events)
        if self._client is not None:
            needs_fallback_flush = True
        if needs_fallback_flush:
            if worker_stopped:
                self._flush_all_without_worker(timeout=self.shutdown_flush_timeout)
            else:
                logger.warning(
                    "Skipping fallback shutdown flush because worker thread is still running"
                )

        with self._lock:
            remaining = len(self._events)
            if remaining > 0:
                self._events_dropped += remaining
                self._events.clear()
                logger.warning("Dropped %d unsent events during shutdown", remaining)
            events_sent = self._events_sent
            events_dropped = self._events_dropped
            flush_count = self._flush_count

        logger.info(
            f"EventBatcher shutdown: sent={events_sent}, "
            f"dropped={events_dropped}, flushes={flush_count}"
        )

    def get_stats(self) -> dict:
        """Get batcher statistics."""
        with self._lock:
            pending = len(self._events)
            events_sent = self._events_sent
            events_dropped = self._events_dropped
            flush_count = self._flush_count
            running = self._running
        return {
            "events_sent": events_sent,
            "events_dropped": events_dropped,
            "events_pending": pending,
            "flush_count": flush_count,
            "running": running,
        }


# Global batcher instance
_batcher: EventBatcher | None = None


def get_event_batcher() -> EventBatcher | None:
    """
    Get the global EventBatcher instance.

    Returns:
        EventBatcher if observability is enabled, None otherwise
    """
    return _batcher


def init_observability(
    server_url: str | None = None,
    api_key: str | None = None,
    enabled: bool | None = None,
) -> EventBatcher | None:
    """
    Initialize observability system.

    Called automatically by agent_control.init() if observability is enabled.

    Args:
        server_url: Server URL for sending events
        api_key: API key for authentication
        enabled: Override AGENT_CONTROL_OBSERVABILITY_ENABLED

    Returns:
        EventBatcher instance if enabled, None otherwise
    """
    global _batcher

    # Check if enabled
    is_enabled = enabled if enabled is not None else get_settings().observability_enabled

    if not is_enabled:
        logger.debug("Observability disabled")
        return None

    if _batcher is not None:
        logger.debug("Observability already initialized")
        return _batcher

    # Create batcher
    _batcher = EventBatcher(server_url=server_url, api_key=api_key)
    _batcher.start()

    # Register shutdown handler
    atexit.register(_batcher.shutdown)

    logger.info("Observability initialized")
    return _batcher


def add_event(event: ControlExecutionEvent) -> bool:
    """
    Add an event to the global batcher.

    Args:
        event: Control execution event to add

    Returns:
        True if added, False if observability disabled or event dropped
    """
    if _batcher is None:
        return False
    return _batcher.add_event(event)


def sync_shutdown_observability() -> None:
    """Synchronously shut down observability and flush remaining events."""
    global _batcher
    if _batcher is not None:
        _batcher.shutdown()
        _batcher = None


async def shutdown_observability() -> None:
    """
    Shutdown observability and flush remaining events.

    Call this before process exit for clean shutdown.
    """
    # Delegate to the sync implementation off the event loop thread.
    await asyncio.to_thread(sync_shutdown_observability)


def is_observability_enabled() -> bool:
    """Check if observability is enabled and initialized."""
    return _batcher is not None


def log_span_start(
    trace_id: str,
    span_id: str,
    function_name: str,
    agent_name: str | None = None,
) -> None:
    """
    Log span start for debugging and correlation.

    Args:
        trace_id: Trace ID (full 32-char hex)
        span_id: Span ID (full 16-char hex)
        function_name: Name of the function being traced
        agent_name: Optional agent name
    """
    if not _should_log("span_start"):
        return

    agent_part = f" agent={agent_name}" if agent_name else ""
    logger.info(f"[trace:{trace_id}] [span:{span_id}] Span started: {function_name}{agent_part}")


def log_span_end(
    trace_id: str,
    span_id: str,
    function_name: str,
    duration_ms: float,
    executions: int = 0,
    matches: int = 0,
    non_matches: int = 0,
    errors: int = 0,
    actions: dict[str, int] | None = None,
) -> None:
    """
    Log span end with summary stats.

    Args:
        trace_id: Trace ID (full 32-char hex)
        span_id: Span ID (full 16-char hex)
        function_name: Name of the function being traced
        duration_ms: Total duration in milliseconds
        executions: Total number of control executions
        matches: Number of controls that matched
        non_matches: Number of controls that didn't match
        errors: Number of errors during evaluation
        actions: Dict of action counts (e.g., {"deny": 2, "warn": 1})
    """
    if not _should_log("span_end"):
        return

    actions_str = ""
    if actions:
        actions_str = " actions={" + ", ".join(f"{k}:{v}" for k, v in actions.items()) + "}"

    logger.info(
        f"[trace:{trace_id}] [span:{span_id}] Span completed: {function_name} "
        f"duration={duration_ms:.1f}ms exec={executions} "
        f"match={matches} non_match={non_matches} errors={errors}{actions_str}"
    )


def log_control_evaluation(
    trace_id: str,
    span_id: str,
    control_name: str,
    matched: bool,
    action: str,
    confidence: float,
    duration_ms: float | None = None,
    control_execution_id: str | None = None,
    check_stage: str | None = None,
) -> None:
    """
    Log individual control evaluation for debugging.

    This allows users to search logs by control_execution_id from the UI.

    Args:
        trace_id: Trace ID (full 32-char hex)
        span_id: Span ID (full 16-char hex)
        control_name: Name of the control that was evaluated
        matched: Whether the control matched
        action: Action taken (allow, deny, warn, log)
        confidence: Confidence score (0.0-1.0)
        duration_ms: Evaluation duration in milliseconds
        control_execution_id: Unique ID for this control execution
        check_stage: Check stage (pre or post)
    """
    if not _should_log("control_eval"):
        return

    parts = [
        f"[trace:{trace_id}]",
        f"[span:{span_id}]",
        f"[control:{control_name}]",
    ]

    if check_stage:
        parts.append(f"stage={check_stage}")

    parts.append(f"matched={matched}")

    # Only show action if the control matched (action was actually taken)
    if matched:
        parts.append(f"action={action}")

    parts.append(f"confidence={confidence:.2f}")

    if duration_ms is not None:
        parts.append(f"duration={duration_ms:.1f}ms")

    if control_execution_id:
        parts.append(f"exec_id={control_execution_id}")

    logger.info(" ".join(parts))
