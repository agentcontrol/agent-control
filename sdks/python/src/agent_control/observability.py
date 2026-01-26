"""
Event batching and transmission for Agent Control observability.

This module provides an EventBatcher that collects control execution events
and sends them to the server in batches for efficient transmission.

Usage:
    from agent_control.observability import get_event_batcher, add_event

    # Add an event (usually done automatically by @control decorator)
    add_event(event)

    # On shutdown, flush remaining events
    await shutdown_observability()

Configuration (Environment Variables):
    AGENT_CONTROL_OBSERVABILITY_ENABLED: Enable observability (default: false)
    AGENT_CONTROL_BATCH_SIZE: Max events per batch (default: 100)
    AGENT_CONTROL_FLUSH_INTERVAL: Seconds between flushes (default: 10.0)

    # Logging Configuration
    AGENT_CONTROL_LOG_ENABLED: Master switch for logging (default: true)
    AGENT_CONTROL_LOG_LEVEL: Log level - DEBUG, INFO, WARNING, ERROR (default: INFO)
    AGENT_CONTROL_LOG_SPAN_START: Log span start events (default: true)
    AGENT_CONTROL_LOG_SPAN_END: Log span end events (default: true)
    AGENT_CONTROL_LOG_CONTROL_EVAL: Log per-control evaluation (default: true)
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_control.settings import configure_settings, get_settings

if TYPE_CHECKING:
    import httpx
    from agent_control_models import ControlExecutionEvent

logger = logging.getLogger(__name__)

# =============================================================================
# Logging Configuration (backwards-compatible wrapper around settings)
# =============================================================================


@dataclass
class LogConfig:
    """
    Configuration for observability logging.

    This class provides backwards compatibility with the original API.
    Settings are stored in the centralized SDKSettings instance.
    """

    enabled: bool = field(default_factory=lambda: get_settings().log_enabled)
    level: str = field(default_factory=lambda: get_settings().log_level)
    span_start: bool = field(default_factory=lambda: get_settings().log_span_start)
    span_end: bool = field(default_factory=lambda: get_settings().log_span_end)
    control_eval: bool = field(default_factory=lambda: get_settings().log_control_eval)

    @classmethod
    def from_env(cls) -> LogConfig:
        """Load configuration from environment variables (via settings)."""
        return cls(
            enabled=get_settings().log_enabled,
            level=get_settings().log_level,
            span_start=get_settings().log_span_start,
            span_end=get_settings().log_span_end,
            control_eval=get_settings().log_control_eval,
        )

    def update(self, config_dict: dict[str, Any]) -> None:
        """Update configuration from a dictionary."""
        # Map old names to new setting names
        mapping = {
            "enabled": "log_enabled",
            "level": "log_level",
            "span_start": "log_span_start",
            "span_end": "log_span_end",
            "control_eval": "log_control_eval",
        }
        updates = {}
        for old_key, new_key in mapping.items():
            if old_key in config_dict:
                value = config_dict[old_key]
                if old_key == "level":
                    value = str(value).upper()
                else:
                    value = bool(value)
                updates[new_key] = value
                setattr(self, old_key, value)

        if updates:
            configure_settings(**updates)


# Global logging configuration (for backwards compatibility)
_log_config = LogConfig.from_env()


def configure_logging(config: dict[str, Any] | None = None) -> LogConfig:
    """
    Configure observability logging.

    Can be called programmatically to override environment variable defaults.

    Args:
        config: Dictionary with logging options:
            - enabled: bool - Master switch (default: True)
            - level: str - Log level (default: "INFO")
            - span_start: bool - Log span start (default: True)
            - span_end: bool - Log span end (default: True)
            - control_eval: bool - Log per-control evaluation (default: True)

    Returns:
        Current LogConfig after applying changes

    Example:
        configure_logging({
            "enabled": True,
            "control_eval": False,  # Disable per-control logging
        })
    """
    global _log_config
    if config:
        _log_config.update(config)
    return _log_config


def get_log_config() -> LogConfig:
    """Get the current logging configuration."""
    return _log_config


def _should_log(log_type: str) -> bool:
    """Check if a specific log type should be emitted."""
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
    - Flush interval timeout (default: 10 seconds)

    Thread-safe and async-safe.

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

        # Thread-safe event storage
        self._events: list[ControlExecutionEvent] = []
        self._lock = threading.Lock()

        # Background flush task
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

        # Reusable HTTP client for connection pooling
        self._client: httpx.AsyncClient | None = None

        # Stats
        self._events_sent = 0
        self._events_dropped = 0
        self._flush_count = 0

    def start(self) -> None:
        """Start the background flush task."""
        if self._running:
            return

        self._running = True

        # Try to get current event loop, create new if needed
        try:
            self._loop = asyncio.get_running_loop()
            self._flush_task = self._loop.create_task(self._flush_loop())
        except RuntimeError:
            # No running loop - will start when first event is added in async context
            pass

        logger.debug("EventBatcher started")

    def stop(self) -> None:
        """Stop the background flush task."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            self._flush_task = None
        logger.debug("EventBatcher stopped")

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def add_event(self, event: ControlExecutionEvent) -> bool:
        """
        Add an event to the batch.

        Thread-safe and non-blocking.

        Args:
            event: Control execution event to add

        Returns:
            True if event was added, False if dropped (e.g., queue full)
        """
        with self._lock:
            # Limit queue size to prevent memory issues
            if len(self._events) >= self.batch_size * 10:
                self._events_dropped += 1
                logger.warning("Event dropped: queue full")
                return False

            self._events.append(event)

            # Trigger flush if batch is full
            if len(self._events) >= self.batch_size:
                self._schedule_flush()

            return True

    def _schedule_flush(self) -> None:
        """Schedule an immediate flush (non-blocking)."""
        if self._loop and self._running:
            try:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._flush())
                )
            except RuntimeError:
                pass

    async def _flush_loop(self) -> None:
        """Background task that flushes events periodically."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Flush loop error: {e}")

    async def _flush(self) -> None:
        """Flush current batch to server."""
        # Get events to send
        with self._lock:
            if not self._events:
                return
            events_to_send = self._events[:self.batch_size]
            self._events = self._events[self.batch_size:]

        if not events_to_send:
            return

        # Send to server
        success = await self._send_batch(events_to_send)

        if success:
            self._events_sent += len(events_to_send)
            self._flush_count += 1
            logger.debug(
                f"Flushed {len(events_to_send)} events "
                f"(total sent: {self._events_sent})"
            )
        else:
            # Re-queue events on failure (at front for retry)
            with self._lock:
                self._events = events_to_send + self._events
            logger.warning(f"Failed to send batch, re-queued {len(events_to_send)} events")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client for connection pooling."""
        if self._client is None:
            import httpx
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
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed, cannot send events")
            return False

        url = f"{self.server_url}/api/v1/observability/events"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        # Serialize events
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

            # Wait before retry
            if attempt < get_settings().max_retries - 1:
                await asyncio.sleep(get_settings().retry_delay * (attempt + 1))

        return False

    async def flush_all(self) -> None:
        """Flush all remaining events and close the client."""
        while True:
            with self._lock:
                if not self._events:
                    break
            await self._flush()
        # Close the HTTP client after flushing
        await self.close()

    def shutdown(self) -> None:
        """
        Synchronous shutdown - flush remaining events.

        Called on process exit via atexit.
        """
        self.stop()

        with self._lock:
            remaining = len(self._events)

        if remaining > 0:
            logger.info(f"Flushing {remaining} remaining events on shutdown...")

            # Try to flush synchronously using asyncio.run() for robust lifecycle handling
            try:
                asyncio.run(self.flush_all())
            except Exception as e:
                logger.error(f"Error during shutdown flush: {e}")
                self._events_dropped += remaining

        logger.info(
            f"EventBatcher shutdown: sent={self._events_sent}, "
            f"dropped={self._events_dropped}, flushes={self._flush_count}"
        )

    def get_stats(self) -> dict:
        """Get batcher statistics."""
        with self._lock:
            pending = len(self._events)
        return {
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
            "events_pending": pending,
            "flush_count": self._flush_count,
            "running": self._running,
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


async def shutdown_observability() -> None:
    """
    Shutdown observability and flush remaining events.

    Call this before process exit for clean shutdown.
    """
    global _batcher
    if _batcher is not None:
        await _batcher.flush_all()
        _batcher.stop()
        _batcher = None


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
