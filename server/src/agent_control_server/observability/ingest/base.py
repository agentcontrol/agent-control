"""Base interfaces for event ingestion.

This module defines the EventIngestor protocol that all event ingestors
must implement. The protocol is simple enough that users can easily
create custom implementations (e.g., QueuedEventIngestor, RedisEventIngestor).
"""

from typing import Protocol, runtime_checkable

from agent_control_models.observability import ControlExecutionEvent
from pydantic import BaseModel, Field


class IngestResult(BaseModel):
    """Result of an event ingestion operation.

    Attributes:
        received: Number of events received
        processed: Number of events successfully processed
        dropped: Number of events dropped (e.g., due to errors)
    """

    received: int = Field(..., ge=0, description="Number of events received")
    processed: int = Field(..., ge=0, description="Number of events processed")
    dropped: int = Field(..., ge=0, description="Number of events dropped")


@runtime_checkable
class EventIngestor(Protocol):
    """Entry point for observability events from SDK or server.

    This protocol defines the interface for event ingestion. Implementations
    can process events synchronously (DirectEventIngestor) or buffer them
    for async processing (custom QueuedEventIngestor, RedisEventIngestor, etc.).

    Example implementations:
        - DirectEventIngestor: Processes immediately, adds ~5-20ms latency
        - QueuedEventIngestor: Buffers in asyncio.Queue, background worker
        - RedisEventIngestor: Pushes to Redis for external worker processing
        - KafkaEventIngestor: Pushes to Kafka topic
    """

    async def ingest(self, events: list[ControlExecutionEvent]) -> IngestResult:
        """Ingest events. Returns counts of received/processed/dropped.

        Args:
            events: List of control execution events to ingest

        Returns:
            IngestResult with counts of received, processed, and dropped events
        """
        ...

    async def flush(self) -> None:
        """Flush any buffered events (for graceful shutdown).

        For DirectEventIngestor, this is a no-op since events are processed
        immediately. For buffered implementations, this should wait until
        all pending events are processed.
        """
        ...
