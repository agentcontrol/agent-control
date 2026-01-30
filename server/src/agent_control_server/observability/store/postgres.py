"""PostgreSQL event store implementation.

This module provides the PostgresEventStore, which stores raw events
in PostgreSQL with JSONB and performs aggregation at query time.

Performance characteristics:
- store(): ~5-10ms for batch of 100 events
- query_stats(): ~10-200ms depending on time range and event count
- query_events(): ~10-50ms with index-backed filtering
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agent_control_models.observability import (
    ControlExecutionEvent,
    ControlStats,
    EventQueryRequest,
    EventQueryResponse,
    TimeseriesBucket,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .base import EventStore, StatsResult

logger = logging.getLogger(__name__)


# =============================================================================
# SQL Aggregation Expressions
# =============================================================================
# These constants define the JSONB-based aggregation expressions used in stats
# queries. Centralizing them ensures consistency and makes maintenance easier.

# Count expressions
SQL_EXECUTION_COUNT = "COUNT(*)"

SQL_MATCH_COUNT = """SUM(CASE WHEN (data->>'matched')::boolean
    AND data->>'error_message' IS NULL THEN 1 ELSE 0 END)"""

SQL_NON_MATCH_COUNT = """SUM(CASE WHEN NOT (data->>'matched')::boolean
    AND data->>'error_message' IS NULL THEN 1 ELSE 0 END)"""

SQL_ERROR_COUNT = """SUM(CASE WHEN data->>'error_message' IS NOT NULL
    THEN 1 ELSE 0 END)"""

# Action count expressions (only count when matched)
SQL_ALLOW_COUNT = """SUM(CASE WHEN (data->>'matched')::boolean
    AND data->>'action' = 'allow' THEN 1 ELSE 0 END)"""

SQL_DENY_COUNT = """SUM(CASE WHEN (data->>'matched')::boolean
    AND data->>'action' = 'deny' THEN 1 ELSE 0 END)"""

SQL_WARN_COUNT = """SUM(CASE WHEN (data->>'matched')::boolean
    AND data->>'action' = 'warn' THEN 1 ELSE 0 END)"""

SQL_LOG_COUNT = """SUM(CASE WHEN (data->>'matched')::boolean
    AND data->>'action' = 'log' THEN 1 ELSE 0 END)"""

# Average expressions
SQL_AVG_CONFIDENCE = "AVG((data->>'confidence')::float)"

SQL_AVG_DURATION = """AVG((data->>'execution_duration_ms')::float) FILTER (
    WHERE data->>'execution_duration_ms' IS NOT NULL)"""

# Combined aggregation columns (for SELECT statements)
SQL_STATS_AGGREGATIONS = f"""
    {SQL_EXECUTION_COUNT} as execution_count,
    {SQL_MATCH_COUNT} as match_count,
    {SQL_NON_MATCH_COUNT} as non_match_count,
    {SQL_ERROR_COUNT} as error_count,
    {SQL_ALLOW_COUNT} as allow_count,
    {SQL_DENY_COUNT} as deny_count,
    {SQL_WARN_COUNT} as warn_count,
    {SQL_LOG_COUNT} as log_count,
    {SQL_AVG_CONFIDENCE} as avg_confidence,
    {SQL_AVG_DURATION} as avg_duration_ms"""


class PostgresEventStore(EventStore):
    """PostgreSQL-based event store with JSONB storage and query-time aggregation.

    This implementation stores raw events with:
    - Indexed columns (control_execution_id, timestamp, agent_uuid) for efficient filtering
    - JSONB 'data' column containing the full event for flexible querying

    Stats are computed at query time from raw events, which is fast enough
    for most use cases (sub-200ms for 1-hour windows).

    Attributes:
        session_maker: SQLAlchemy async session maker
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        """Initialize the store.

        Args:
            session_maker: SQLAlchemy async session maker
        """
        self.session_maker = session_maker

    async def store(self, events: list[ControlExecutionEvent]) -> int:
        """Store raw events in PostgreSQL.

        Uses batch insert with ON CONFLICT DO NOTHING for idempotency.
        The simplified schema stores only 4 columns:
        - control_execution_id (PK)
        - timestamp (indexed)
        - agent_uuid (indexed)
        - data (JSONB containing full event)

        Args:
            events: List of control execution events to store

        Returns:
            Number of events successfully stored
        """
        if not events:
            return 0

        # Build values for batch insert (only 4 columns)
        values = []
        for event in events:
            # Serialize the full event to JSONB
            event_data = event.model_dump(mode="json")

            values.append({
                "control_execution_id": event.control_execution_id,
                "timestamp": event.timestamp,
                "agent_uuid": event.agent_uuid,
                "data": json.dumps(event_data),
            })

        async with self.session_maker() as session:
            # Batch insert with minimal columns
            await session.execute(
                text("""
                    INSERT INTO control_execution_events (
                        control_execution_id, timestamp, agent_uuid, data
                    ) VALUES (
                        :control_execution_id, :timestamp, :agent_uuid,
                        CAST(:data AS JSONB)
                    )
                    ON CONFLICT (control_execution_id) DO NOTHING
                """),
                values,
            )
            await session.commit()

        logger.debug(f"Stored {len(events)} events")
        return len(events)

    async def query_stats(
        self,
        agent_uuid: UUID,
        time_range: timedelta,
        control_id: int | None = None,
        include_timeseries: bool = False,
        bucket_size: timedelta | None = None,
    ) -> StatsResult:
        """Query stats aggregated at query time from raw events.

        Optimized single-query implementation that fetches both per-control stats
        and time-series data in one database round-trip using a CTE.

        For time-series, uses generate_series to create all bucket timestamps
        and LEFT JOINs with aggregated data to include empty buckets.

        Args:
            agent_uuid: UUID of the agent to query stats for
            time_range: Time range to aggregate over (from now)
            control_id: Optional control ID to filter by
            include_timeseries: Whether to include time-series data
            bucket_size: Bucket size for time-series (required if include_timeseries=True)

        Returns:
            StatsResult with per-control and total statistics
        """
        now = datetime.now(UTC)
        cutoff = now - time_range

        params: dict = {
            "agent_uuid": agent_uuid,
            "cutoff": cutoff,
        }

        control_filter = ""
        if control_id is not None:
            control_filter = "AND (data->>'control_id')::int = :control_id"
            params["control_id"] = control_id

        # Build combined query with CTE
        if include_timeseries and bucket_size:
            bucket_interval = self._timedelta_to_interval(bucket_size)
            params["bucket_interval"] = bucket_interval
            params["now"] = now

            # Single query that returns both per-control stats and time-series
            # Uses UNION ALL with a discriminator column
            query = text(f"""
                WITH filtered_events AS (
                    SELECT timestamp, data
                    FROM control_execution_events
                    WHERE agent_uuid = :agent_uuid
                      AND timestamp >= :cutoff
                      {control_filter}
                ),
                -- Per-control aggregation
                control_stats AS (
                    SELECT
                        'control' as query_type,
                        (data->>'control_id')::int as control_id,
                        data->>'control_name' as control_name,
                        NULL::timestamptz as bucket,
                        {SQL_STATS_AGGREGATIONS}
                    FROM filtered_events
                    GROUP BY data->>'control_id', data->>'control_name'
                ),
                -- Generate all bucket timestamps
                all_buckets AS (
                    SELECT generate_series(
                        :cutoff,
                        :now - CAST(:bucket_interval AS interval),
                        CAST(:bucket_interval AS interval)
                    ) as bucket
                ),
                -- Time-series aggregation (only buckets with data)
                bucket_stats AS (
                    SELECT
                        date_bin(CAST(:bucket_interval AS interval), timestamp, :cutoff) as bucket,
                        {SQL_STATS_AGGREGATIONS}
                    FROM filtered_events
                    GROUP BY date_bin(CAST(:bucket_interval AS interval), timestamp, :cutoff)
                ),
                -- Join with all buckets to fill empty ones
                timeseries AS (
                    SELECT
                        'timeseries' as query_type,
                        NULL::int as control_id,
                        NULL::text as control_name,
                        ab.bucket,
                        COALESCE(bs.execution_count, 0) as execution_count,
                        COALESCE(bs.match_count, 0) as match_count,
                        COALESCE(bs.non_match_count, 0) as non_match_count,
                        COALESCE(bs.error_count, 0) as error_count,
                        COALESCE(bs.allow_count, 0) as allow_count,
                        COALESCE(bs.deny_count, 0) as deny_count,
                        COALESCE(bs.warn_count, 0) as warn_count,
                        COALESCE(bs.log_count, 0) as log_count,
                        bs.avg_confidence,
                        bs.avg_duration_ms
                    FROM all_buckets ab
                    LEFT JOIN bucket_stats bs ON ab.bucket = bs.bucket
                )
                -- Return control stats first, then timeseries
                -- Wrap in subquery to allow ORDER BY with expressions
                SELECT * FROM (
                    SELECT * FROM control_stats
                    UNION ALL
                    SELECT * FROM timeseries
                ) combined
                ORDER BY query_type DESC, COALESCE(bucket, '1970-01-01'::timestamptz) ASC
            """)
        else:
            # Simple query without time-series
            query = text(f"""
                SELECT
                    'control' as query_type,
                    (data->>'control_id')::int as control_id,
                    data->>'control_name' as control_name,
                    NULL::timestamptz as bucket,
                    {SQL_STATS_AGGREGATIONS}
                FROM control_execution_events
                WHERE agent_uuid = :agent_uuid
                  AND timestamp >= :cutoff
                  {control_filter}
                GROUP BY data->>'control_id', data->>'control_name'
                ORDER BY execution_count DESC
            """)

        async with self.session_maker() as session:
            result = await session.execute(query, params)
            rows = result.fetchall()

        # Parse results - control stats first, then timeseries
        stats = []
        timeseries: list[TimeseriesBucket] | None = None
        total_executions = 0
        total_matches = 0
        total_non_matches = 0
        total_errors = 0
        action_counts: dict[str, int] = {"allow": 0, "deny": 0, "warn": 0, "log": 0}

        for row in rows:
            if row.query_type == "control":
                control_stats = ControlStats(
                    control_id=row.control_id,
                    control_name=row.control_name,
                    execution_count=row.execution_count,
                    match_count=row.match_count,
                    non_match_count=row.non_match_count,
                    error_count=row.error_count,
                    allow_count=row.allow_count,
                    deny_count=row.deny_count,
                    warn_count=row.warn_count,
                    log_count=row.log_count,
                    avg_confidence=row.avg_confidence or 0.0,
                    avg_duration_ms=row.avg_duration_ms,
                )
                stats.append(control_stats)

                total_executions += row.execution_count
                total_matches += row.match_count
                total_non_matches += row.non_match_count
                total_errors += row.error_count
                action_counts["allow"] += row.allow_count
                action_counts["deny"] += row.deny_count
                action_counts["warn"] += row.warn_count
                action_counts["log"] += row.log_count

            elif row.query_type == "timeseries":
                if timeseries is None:
                    timeseries = []

                bucket_action_counts: dict[str, int] = {}
                if row.allow_count > 0:
                    bucket_action_counts["allow"] = row.allow_count
                if row.deny_count > 0:
                    bucket_action_counts["deny"] = row.deny_count
                if row.warn_count > 0:
                    bucket_action_counts["warn"] = row.warn_count
                if row.log_count > 0:
                    bucket_action_counts["log"] = row.log_count

                timeseries.append(TimeseriesBucket(
                    timestamp=row.bucket,
                    execution_count=row.execution_count,
                    match_count=row.match_count,
                    non_match_count=row.non_match_count,
                    error_count=row.error_count,
                    action_counts=bucket_action_counts,
                    avg_confidence=row.avg_confidence,
                    avg_duration_ms=row.avg_duration_ms,
                ))

        # Sort stats by execution count (may be unsorted due to UNION)
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
            timeseries=timeseries,
        )

    def _timedelta_to_interval(self, td: timedelta) -> str:
        """Convert a timedelta to a PostgreSQL interval string.

        Args:
            td: timedelta to convert

        Returns:
            PostgreSQL interval string (e.g., '5 minutes', '1 hour')
        """
        total_seconds = int(td.total_seconds())
        if total_seconds % 3600 == 0:
            hours = total_seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''}"
        elif total_seconds % 60 == 0:
            minutes = total_seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            return f"{total_seconds} seconds"

    async def query_events(self, query: EventQueryRequest) -> EventQueryResponse:
        """Query raw events with filters and pagination.

        Supports filtering by trace_id, span_id, agent_uuid, control_ids,
        actions, matched status, time range, and pagination.

        Filters use JSONB operators for fields stored in the 'data' column,
        except for indexed columns (control_execution_id, timestamp, agent_uuid).

        Args:
            query: Query parameters (filters, pagination)

        Returns:
            EventQueryResponse with matching events and pagination info
        """
        # Build WHERE clauses and params
        where_clauses = []
        params: dict = {}

        # Indexed columns (use direct comparison)
        if query.control_execution_id:
            where_clauses.append("control_execution_id = :control_execution_id")
            params["control_execution_id"] = query.control_execution_id

        if query.agent_uuid:
            where_clauses.append("agent_uuid = :agent_uuid")
            params["agent_uuid"] = query.agent_uuid

        if query.start_time:
            where_clauses.append("timestamp >= :start_time")
            params["start_time"] = query.start_time

        if query.end_time:
            where_clauses.append("timestamp <= :end_time")
            params["end_time"] = query.end_time

        # JSONB fields (use ->> operator)
        if query.trace_id:
            where_clauses.append("data->>'trace_id' = :trace_id")
            params["trace_id"] = query.trace_id

        if query.span_id:
            where_clauses.append("data->>'span_id' = :span_id")
            params["span_id"] = query.span_id

        if query.control_ids:
            where_clauses.append("(data->>'control_id')::int = ANY(:control_ids)")
            params["control_ids"] = query.control_ids

        if query.actions:
            where_clauses.append("data->>'action' = ANY(:actions)")
            params["actions"] = query.actions

        if query.matched is not None:
            where_clauses.append("(data->>'matched')::boolean = :matched")
            params["matched"] = query.matched

        if query.check_stages:
            where_clauses.append("data->>'check_stage' = ANY(:check_stages)")
            params["check_stages"] = query.check_stages

        if query.applies_to:
            where_clauses.append("data->>'applies_to' = ANY(:applies_to)")
            params["applies_to"] = query.applies_to

        # Build WHERE clause
        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

        # Add pagination
        params["limit"] = query.limit
        params["offset"] = query.offset

        async with self.session_maker() as session:
            # Get total count
            count_result = await session.execute(
                text(f"""
                    SELECT COUNT(*) as total
                    FROM control_execution_events
                    WHERE {where_sql}
                """),
                params,
            )
            total = count_result.scalar() or 0

            # Get events
            result = await session.execute(
                text(f"""
                    SELECT data
                    FROM control_execution_events
                    WHERE {where_sql}
                    ORDER BY timestamp DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

        # Parse events from JSONB
        events = []
        for row in rows:
            event_data = row.data
            # If data is already a dict (JSONB auto-parsed), use it directly
            if isinstance(event_data, str):
                event_data = json.loads(event_data)
            events.append(ControlExecutionEvent(**event_data))

        return EventQueryResponse(
            events=events,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )
