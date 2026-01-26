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
    EventQueryRequest,
    EventQueryResponse,
    StatsResponse,
)
from fastapi import APIRouter, Depends, Request

from ..auth import require_api_key
from ..observability.ingest.base import EventIngestor
from ..observability.store.base import EventStore, parse_time_range

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
    time_range: Literal["1m", "5m", "15m", "1h", "24h", "7d"] = "5m",
    control_id: int | None = None,
    store: EventStore = Depends(get_event_store),
) -> StatsResponse:
    """
    Get aggregated control execution statistics.

    Statistics are computed at query time from raw events. This is fast
    enough for most use cases (sub-200ms for 1-hour windows).

    Args:
        agent_uuid: Agent to get stats for
        time_range: Time range (1m, 5m, 15m, 1h, 24h, 7d)
        control_id: Optional filter by specific control
        store: Event store (injected)

    Returns:
        StatsResponse with per-control statistics
    """
    interval = parse_time_range(time_range)
    result = await store.query_stats(agent_uuid, interval, control_id)

    return StatsResponse(
        agent_uuid=agent_uuid,
        time_range=time_range,
        stats=result.stats,
        total_executions=result.total_executions,
        total_matches=result.total_matches,
        total_non_matches=result.total_non_matches,
        total_errors=result.total_errors,
        action_counts=result.action_counts,
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
