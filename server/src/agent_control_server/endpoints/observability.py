"""Observability API endpoints.

This module provides endpoints for:
1. Event ingestion (POST /events) - SDK sends batched events
2. Event queries (POST /events/query) - Query raw events by trace_id, etc.
3. Stats (GET /stats) - Aggregated statistics for dashboards

All endpoints require API key authentication.

Dependencies are stored on app.state during server lifespan (see main.py):
- app.state.event_ingestor: EventIngestor
- app.state.event_store: EventStore
"""

import logging
import time
from typing import Literal, cast
from uuid import UUID

from agent_control_models import (
    BatchEventsRequest,
    BatchEventsResponse,
    ControlStatsResponse,
    EventQueryRequest,
    EventQueryResponse,
    StatsResponse,
    StatsTotals,
)
from fastapi import APIRouter, Depends, Request

from ..auth import require_api_key
from ..observability.ingest.base import EventIngestor
from ..observability.store.base import (
    EventStore,
    TimeRange,
    get_bucket_size,
    parse_time_range,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/observability",
    tags=["observability"],
    dependencies=[Depends(require_api_key)],
)


# =============================================================================
# Dependency Injection (via app.state)
# =============================================================================


def get_event_ingestor(request: Request) -> EventIngestor:
    """Get the event ingestor from app.state."""
    ingestor = getattr(request.app.state, "event_ingestor", None)
    if ingestor is None:
        raise RuntimeError("EventIngestor not initialized - check server startup")
    return cast(EventIngestor, ingestor)


def get_event_store(request: Request) -> EventStore:
    """Get the event store from app.state."""
    store = getattr(request.app.state, "event_store", None)
    if store is None:
        raise RuntimeError("EventStore not initialized - check server startup")
    return cast(EventStore, store)


# =============================================================================
# Event Ingestion
# =============================================================================


@router.post("/events", status_code=202, response_model=BatchEventsResponse)
async def ingest_events(
    request: BatchEventsRequest,
    ingestor: EventIngestor = Depends(get_event_ingestor),
) -> BatchEventsResponse:
    """
    Ingest batched control execution events.

    Events are stored directly to the database with ~5-20ms latency.

    Args:
        request: Batch of events to ingest
        ingestor: Event ingestor (injected)

    Returns:
        BatchEventsResponse with counts of received/processed/dropped
    """
    start_time = time.perf_counter()

    result = await ingestor.ingest(request.events)

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.debug(
        f"Ingested {result.received} events "
        f"(processed={result.processed}, dropped={result.dropped}) in {duration_ms:.2f}ms"
    )

    # Determine status
    status: Literal["queued", "partial", "failed"]
    if result.dropped == 0:
        status = "queued"  # Keep "queued" for API compatibility
    elif result.processed > 0:
        status = "partial"
    else:
        status = "failed"

    return BatchEventsResponse(
        received=result.received,
        enqueued=result.processed,  # Map to "enqueued" for API compatibility
        dropped=result.dropped,
        status=status,
    )


# =============================================================================
# Event Queries (Raw Events)
# =============================================================================


@router.post("/events/query", response_model=EventQueryResponse)
async def query_events(
    request: EventQueryRequest,
    store: EventStore = Depends(get_event_store),
) -> EventQueryResponse:
    """
    Query raw control execution events.

    Supports filtering by:
    - trace_id: Get all events for a request
    - span_id: Get all events for a function call
    - control_execution_id: Get a specific event
    - agent_uuid: Filter by agent
    - control_ids: Filter by controls
    - actions: Filter by actions (allow, deny, warn, log)
    - matched: Filter by matched status
    - check_stages: Filter by check stage (pre, post)
    - applies_to: Filter by call type (llm_call, tool_call)
    - start_time/end_time: Filter by time range

    Results are paginated with limit/offset.

    Args:
        request: Query parameters
        store: Event store (injected)

    Returns:
        EventQueryResponse with matching events and pagination info
    """
    return await store.query_events(request)


# =============================================================================
# Statistics (Query-Time Aggregation)
# =============================================================================


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    agent_uuid: UUID,
    time_range: TimeRange = "5m",
    include_timeseries: bool = False,
    store: EventStore = Depends(get_event_store),
) -> StatsResponse:
    """
    Get agent-level aggregated statistics.

    Returns totals across all controls plus per-control breakdown.
    Use /stats/controls/{control_id} for single control stats.

    Args:
        agent_uuid: Agent to get stats for
        time_range: Time range (1m, 5m, 15m, 1h, 24h, 7d, 30d, 180d, 365d)
        include_timeseries: Include time-series data points for trend visualization
        store: Event store (injected)

    Returns:
        StatsResponse with agent-level totals and per-control breakdown
    """
    interval = parse_time_range(time_range)
    bucket_size = get_bucket_size(time_range) if include_timeseries else None

    result = await store.query_stats(
        agent_uuid,
        interval,
        control_id=None,
        include_timeseries=include_timeseries,
        bucket_size=bucket_size,
    )

    return StatsResponse(
        agent_uuid=agent_uuid,
        time_range=time_range,
        totals=StatsTotals(
            execution_count=result.total_executions,
            match_count=result.total_matches,
            non_match_count=result.total_non_matches,
            error_count=result.total_errors,
            action_counts=result.action_counts,
            timeseries=result.timeseries,
        ),
        controls=result.stats,
    )


@router.get("/stats/controls/{control_id}", response_model=ControlStatsResponse)
async def get_control_stats(
    control_id: int,
    agent_uuid: UUID,
    time_range: TimeRange = "5m",
    include_timeseries: bool = False,
    store: EventStore = Depends(get_event_store),
) -> ControlStatsResponse:
    """
    Get statistics for a single control.

    Returns stats for the specified control with optional time-series.

    Args:
        control_id: Control ID to get stats for
        agent_uuid: Agent to get stats for
        time_range: Time range (1m, 5m, 15m, 1h, 24h, 7d, 30d, 180d, 365d)
        include_timeseries: Include time-series data points for trend visualization
        store: Event store (injected)

    Returns:
        ControlStatsResponse with control stats and optional timeseries
    """
    interval = parse_time_range(time_range)
    bucket_size = get_bucket_size(time_range) if include_timeseries else None

    result = await store.query_stats(
        agent_uuid,
        interval,
        control_id=control_id,
        include_timeseries=include_timeseries,
        bucket_size=bucket_size,
    )

    # Get control name from the stats (should be exactly one)
    control_name = result.stats[0].control_name if result.stats else f"control-{control_id}"

    return ControlStatsResponse(
        agent_uuid=agent_uuid,
        time_range=time_range,
        control_id=control_id,
        control_name=control_name,
        stats=StatsTotals(
            execution_count=result.total_executions,
            match_count=result.total_matches,
            non_match_count=result.total_non_matches,
            error_count=result.total_errors,
            action_counts=result.action_counts,
            timeseries=result.timeseries,
        ),
    )


# =============================================================================
# Health / Status
# =============================================================================


@router.get("/status")
async def get_status(request: Request) -> dict:
    """
    Get observability system status.

    Returns basic health information.
    """
    return {
        "status": "ok",
        "ingestor_initialized": hasattr(request.app.state, "event_ingestor"),
        "store_initialized": hasattr(request.app.state, "event_store"),
    }
