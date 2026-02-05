"""Direct event ingestor implementation.

This module provides the DirectEventIngestor, which processes events
immediately (synchronously) by storing them directly to the EventStore.

For high-throughput scenarios, users can implement their own buffered
ingestor (e.g., QueuedEventIngestor, RedisEventIngestor).
"""

import json
import logging

from agent_control_models.observability import ControlExecutionEvent

from ..store.base import EventStore
from .base import EventIngestor, IngestResult

logger = logging.getLogger(__name__)


class DirectEventIngestor(EventIngestor):
    """Processes events immediately by storing them to the EventStore.

    This is the simplest ingestor implementation. Events are stored
    directly to the database, adding ~5-20ms latency per batch.

    For use cases that require lower latency or higher throughput,
    implement a custom buffered ingestor (e.g., QueuedEventIngestor).

    Attributes:
        store: The EventStore to write events to
        log_to_stdout: Whether to log events as structured JSON
    """

    def __init__(self, store: EventStore, log_to_stdout: bool = False):
        """Initialize the ingestor.

        Args:
            store: The EventStore to write events to
            log_to_stdout: Whether to log events as structured JSON (default: False)
        """
        self.store = store
        self.log_to_stdout = log_to_stdout

    async def ingest(self, events: list[ControlExecutionEvent]) -> IngestResult:
        """Ingest events by storing them directly to the EventStore.

        Args:
            events: List of control execution events to ingest

        Returns:
            IngestResult with counts of received, processed, and dropped events
        """
        if not events:
            return IngestResult(received=0, processed=0, dropped=0)

        received = len(events)
        processed = 0
        dropped = 0

        try:
            # Store events
            processed = await self.store.store(events)

            # Log to stdout if enabled
            if self.log_to_stdout:
                self._log_events(events)

        except Exception:
            logger.error("Failed to store events", exc_info=True)
            dropped = received

        return IngestResult(
            received=received,
            processed=processed,
            dropped=dropped,
        )

    async def flush(self) -> None:
        """Flush any buffered events.

        For DirectEventIngestor, this is a no-op since events are
        processed immediately.
        """
        pass

    def _log_events(self, events: list[ControlExecutionEvent]) -> None:
        """Log events as structured JSON to stdout.

        Args:
            events: Events to log
        """
        for event in events:
            log_data = {
                "event_type": "control_execution",
                "trace_id": event.trace_id,
                "span_id": event.span_id,
                "agent_uuid": str(event.agent_uuid),
                "agent_name": event.agent_name,
                "control_id": event.control_id,
                "control_name": event.control_name,
                "check_stage": event.check_stage,
                "applies_to": event.applies_to,
                "action": event.action,
                "matched": event.matched,
                "confidence": event.confidence,
                "timestamp": event.timestamp.isoformat(),
            }
            logger.info(json.dumps(log_data))
