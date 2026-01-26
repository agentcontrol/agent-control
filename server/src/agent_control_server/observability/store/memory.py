"""In-memory event store implementation for testing.

This module provides the MemoryEventStore, which stores events in memory
for testing purposes. It implements the same interface as PostgresEventStore
but without any database dependencies.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agent_control_models.observability import (
    ControlExecutionEvent,
    ControlStats,
    EventQueryRequest,
    EventQueryResponse,
)

from .base import EventStore, StatsResult


class MemoryEventStore(EventStore):
    """In-memory event store for testing.

    This implementation stores events in a list and performs all operations
    in memory. It's suitable for unit tests and local development.

    Note: This store is not thread-safe and should not be used in production.
    """

    def __init__(self) -> None:
        """Initialize the store."""
        self._events: list[ControlExecutionEvent] = []

    async def store(self, events: list[ControlExecutionEvent]) -> int:
        """Store events in memory.

        Args:
            events: List of control execution events to store

        Returns:
            Number of events stored
        """
        # Deduplicate by control_execution_id
        existing_ids = {e.control_execution_id for e in self._events}
        new_events = [e for e in events if e.control_execution_id not in existing_ids]
        self._events.extend(new_events)
        return len(new_events)

    async def query_stats(
        self,
        agent_uuid: UUID,
        time_range: timedelta,
        control_id: int | None = None,
    ) -> StatsResult:
        """Query stats from in-memory events.

        Args:
            agent_uuid: UUID of the agent to query stats for
            time_range: Time range to aggregate over (from now)
            control_id: Optional control ID to filter by

        Returns:
            StatsResult with per-control and total statistics
        """
        cutoff = datetime.now(UTC) - time_range

        # Filter events
        filtered = [
            e for e in self._events
            if e.agent_uuid == agent_uuid
            and e.timestamp >= cutoff
            and (control_id is None or e.control_id == control_id)
        ]

        # Group by control
        by_control: dict[int, list[ControlExecutionEvent]] = defaultdict(list)
        for event in filtered:
            by_control[event.control_id].append(event)

        # Compute stats per control
        stats = []
        total_executions = 0
        total_matches = 0
        total_non_matches = 0
        total_errors = 0
        action_counts: dict[str, int] = {"allow": 0, "deny": 0, "warn": 0, "log": 0}

        for cid, events in by_control.items():
            execution_count = len(events)
            match_count = sum(1 for e in events if e.matched and not e.error_message)
            non_match_count = sum(1 for e in events if not e.matched and not e.error_message)
            error_count = sum(1 for e in events if e.error_message)
            allow_count = sum(1 for e in events if e.matched and e.action == "allow")
            deny_count = sum(1 for e in events if e.matched and e.action == "deny")
            warn_count = sum(1 for e in events if e.matched and e.action == "warn")
            log_count = sum(1 for e in events if e.matched and e.action == "log")

            confidences = [e.confidence for e in events]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            durations = [
                e.execution_duration_ms for e in events
                if e.execution_duration_ms is not None
            ]
            avg_duration_ms = sum(durations) / len(durations) if durations else None

            control_name = events[0].control_name if events else ""

            control_stats = ControlStats(
                control_id=cid,
                control_name=control_name,
                execution_count=execution_count,
                match_count=match_count,
                non_match_count=non_match_count,
                error_count=error_count,
                allow_count=allow_count,
                deny_count=deny_count,
                warn_count=warn_count,
                log_count=log_count,
                avg_confidence=avg_confidence,
                avg_duration_ms=avg_duration_ms,
            )
            stats.append(control_stats)

            total_executions += execution_count
            total_matches += match_count
            total_non_matches += non_match_count
            total_errors += error_count

            # Accumulate action counts (only for matches)
            action_counts["allow"] += allow_count
            action_counts["deny"] += deny_count
            action_counts["warn"] += warn_count
            action_counts["log"] += log_count

        # Sort by execution count descending
        stats.sort(key=lambda s: s.execution_count, reverse=True)

        # Remove zero counts for cleaner response
        action_counts = {k: v for k, v in action_counts.items() if v > 0}

        return StatsResult(
            stats=stats,
            total_executions=total_executions,
            total_matches=total_matches,
            total_non_matches=total_non_matches,
            total_errors=total_errors,
            action_counts=action_counts,
        )

    async def query_events(self, query: EventQueryRequest) -> EventQueryResponse:
        """Query events from memory with filters and pagination.

        Args:
            query: Query parameters (filters, pagination)

        Returns:
            EventQueryResponse with matching events and pagination info
        """
        filtered = self._events

        # Apply filters
        if query.trace_id:
            filtered = [e for e in filtered if e.trace_id == query.trace_id]

        if query.span_id:
            filtered = [e for e in filtered if e.span_id == query.span_id]

        if query.control_execution_id:
            filtered = [e for e in filtered if e.control_execution_id == query.control_execution_id]

        if query.agent_uuid:
            filtered = [e for e in filtered if e.agent_uuid == query.agent_uuid]

        if query.control_ids:
            filtered = [e for e in filtered if e.control_id in query.control_ids]

        if query.actions:
            filtered = [e for e in filtered if e.action in query.actions]

        if query.matched is not None:
            filtered = [e for e in filtered if e.matched == query.matched]

        if query.check_stages:
            filtered = [e for e in filtered if e.check_stage in query.check_stages]

        if query.applies_to:
            filtered = [e for e in filtered if e.applies_to in query.applies_to]

        if query.start_time:
            filtered = [e for e in filtered if e.timestamp >= query.start_time]

        if query.end_time:
            filtered = [e for e in filtered if e.timestamp <= query.end_time]

        # Sort by timestamp descending
        filtered.sort(key=lambda e: e.timestamp, reverse=True)

        # Get total before pagination
        total = len(filtered)

        # Apply pagination
        start = query.offset
        end = start + query.limit
        paginated = filtered[start:end]

        return EventQueryResponse(
            events=paginated,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    def clear(self) -> None:
        """Clear all stored events (for testing)."""
        self._events.clear()

    @property
    def event_count(self) -> int:
        """Get the number of stored events."""
        return len(self._events)
