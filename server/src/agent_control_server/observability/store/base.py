"""Base interfaces for event storage.

This module defines the EventStore ABC that all event stores must implement.
The interface supports raw event storage and query-time aggregation (no pre-aggregation).

Built-in implementations:
    - PostgresEventStore: Postgres with JSONB storage and query-time aggregation
    - MemoryEventStore: In-memory store for testing

Custom implementations users can create:
    - ClickhouseEventStore: Native JSON + columnar = fast aggregation
    - TimescaleDBEventStore: Time-series optimized Postgres extension
    - ElasticsearchEventStore: Full-text search capabilities
"""

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Literal
from uuid import UUID

from agent_control_models.observability import (
    ControlExecutionEvent,
    ControlStats,
    EventQueryRequest,
    EventQueryResponse,
)
from pydantic import BaseModel, Field


class StatsResult(BaseModel):
    """Result of a stats query.

    Contains per-control statistics and totals, aggregated at query time
    from raw events.

    Invariant: total_executions = total_matches + total_non_matches + total_errors

    Matches have actions (allow, deny, warn, log) tracked in action_counts.
    sum(action_counts.values()) == total_matches

    Attributes:
        stats: List of per-control statistics
        total_executions: Total executions across all controls
        total_matches: Total matches across all controls (evaluator matched)
        total_non_matches: Total non-matches across all controls (evaluator didn't match)
        total_errors: Total errors across all controls (evaluation failed)
        action_counts: Breakdown of actions for matched executions
    """

    stats: list[ControlStats] = Field(default_factory=list, description="Per-control statistics")
    total_executions: int = Field(default=0, ge=0, description="Total executions")
    total_matches: int = Field(default=0, ge=0, description="Total matches")
    total_non_matches: int = Field(default=0, ge=0, description="Total non-matches")
    total_errors: int = Field(default=0, ge=0, description="Total errors")
    action_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Action breakdown for matches: {allow, deny, warn, log}",
    )


# Re-export query types from models for convenience
EventQuery = EventQueryRequest
EventQueryResult = EventQueryResponse


# Time range string to timedelta mapping
TIME_RANGE_MAP: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def parse_time_range(time_range: Literal["1m", "5m", "15m", "1h", "24h", "7d"]) -> timedelta:
    """Convert time range string to timedelta."""
    return TIME_RANGE_MAP[time_range]


class EventStore(ABC):
    """Storage backend for observability events.

    This ABC defines the interface for event storage. Implementations
    store raw events and perform aggregation at query time (no pre-aggregation).

    All methods are async to support both sync and async database drivers.
    """

    @abstractmethod
    async def store(self, events: list[ControlExecutionEvent]) -> int:
        """Store raw events.

        Args:
            events: List of control execution events to store

        Returns:
            Number of events successfully stored
        """
        pass

    @abstractmethod
    async def query_stats(
        self,
        agent_uuid: UUID,
        time_range: timedelta,
        control_id: int | None = None,
    ) -> StatsResult:
        """Query stats (aggregated at query time from raw events).

        Args:
            agent_uuid: UUID of the agent to query stats for
            time_range: Time range to aggregate over (from now)
            control_id: Optional control ID to filter by

        Returns:
            StatsResult with per-control and total statistics
        """
        pass

    @abstractmethod
    async def query_events(self, query: EventQuery) -> EventQueryResult:
        """Query raw events with filters and pagination.

        Args:
            query: Query parameters (filters, pagination)

        Returns:
            EventQueryResult with matching events and pagination info
        """
        pass

    async def close(self) -> None:
        """Close any resources held by the store.

        Override in implementations that need cleanup (e.g., connection pools).
        """
        pass
