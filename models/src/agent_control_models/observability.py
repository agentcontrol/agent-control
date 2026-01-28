"""Observability models for tracking control executions.

This module provides models for:
- Control execution events (what controls ran, with what results)
- Batch event ingestion (SDK -> Server)
- Event queries (filtering and pagination)
- Aggregated statistics (pre-computed metrics)
- Real-time streaming updates
"""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from .base import BaseModel

# =============================================================================
# Core Event Model
# =============================================================================


class ControlExecutionEvent(BaseModel):
    """
    Represents a single control execution event.

    This is the core observability data model, capturing:
    - Identity: control_execution_id, trace_id, span_id (OpenTelemetry-compatible)
    - Context: agent, control, check stage, applies to
    - Result: action taken, whether matched, confidence score
    - Timing: when it happened, how long it took
    - Optional details: evaluator name, selector path, errors, metadata

    Attributes:
        control_execution_id: Unique ID for this specific control execution
        trace_id: OpenTelemetry-compatible trace ID (128-bit hex, 32 chars)
        span_id: OpenTelemetry-compatible span ID (64-bit hex, 16 chars)
        agent_uuid: UUID of the agent that executed the control
        agent_name: Name of the agent (denormalized for queries)
        control_id: Database ID of the control
        control_name: Name of the control (denormalized for queries)
        control_set_id: Optional ID of the control set
        control_set_name: Optional name of the control set
        check_stage: "pre" (before execution) or "post" (after execution)
        applies_to: "llm_call" or "tool_call"
        action: The action taken (allow, deny, warn, log)
        matched: Whether the control evaluator matched
        confidence: Confidence score from the evaluator (0.0-1.0)
        timestamp: When the control was executed (UTC)
        execution_duration_ms: How long the control evaluation took
        evaluator_name: Name of the evaluator used
        selector_path: The selector path used to extract data
        error_message: Error message if evaluation failed
        metadata: Additional metadata for extensibility
    """

    # Unique identifiers (OpenTelemetry-compatible)
    control_execution_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique ID for this control execution",
    )
    trace_id: str = Field(
        ...,
        min_length=1,
        description="Trace ID for distributed tracing (SDK generates OTEL-compatible 32-char hex)",
    )
    span_id: str = Field(
        ...,
        min_length=1,
        description="Span ID for distributed tracing (SDK generates OTEL-compatible 16-char hex)",
    )

    # Agent identity
    agent_uuid: UUID = Field(..., description="UUID of the agent")
    agent_name: str = Field(..., description="Name of the agent (denormalized)")

    # Control info
    control_id: int = Field(..., description="Database ID of the control")
    control_name: str = Field(..., description="Name of the control (denormalized)")

    # Execution context
    check_stage: Literal["pre", "post"] = Field(
        ..., description="Check stage: 'pre' or 'post'"
    )
    applies_to: Literal["llm_call", "tool_call"] = Field(
        ..., description="Type of call: 'llm_call' or 'tool_call'"
    )

    # Result
    action: Literal["allow", "deny", "warn", "log"] = Field(
        ..., description="Action taken by the control"
    )
    matched: bool = Field(
        ..., description="Whether the evaluator matched (True) or not (False)"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0.0 to 1.0)"
    )

    # Timing
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the control was executed (UTC)",
    )
    execution_duration_ms: float | None = Field(
        default=None, ge=0, description="Execution duration in milliseconds"
    )

    # Optional details
    evaluator_name: str | None = Field(
        default=None, description="Name of the evaluator used"
    )
    selector_path: str | None = Field(
        default=None, description="Selector path used to extract data"
    )
    error_message: str | None = Field(
        default=None, description="Error message if evaluation failed"
    )

    # Extensibility
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, v: str) -> str:
        """
        Validate trace_id is non-empty.

        We use lenient validation to support different tracing backends
        (OTEL, X-Ray, Jaeger, etc.) and user-provided trace IDs.
        The SDK generates OTEL-compatible IDs (32-char hex), but we accept
        any non-empty string for flexibility.
        """
        if not v or not v.strip():
            raise ValueError("trace_id cannot be empty")
        return v

    @field_validator("span_id")
    @classmethod
    def validate_span_id(cls, v: str) -> str:
        """
        Validate span_id is non-empty.

        We use lenient validation to support different tracing backends
        (OTEL, X-Ray, Jaeger, etc.) and user-provided span IDs.
        The SDK generates OTEL-compatible IDs (16-char hex), but we accept
        any non-empty string for flexibility.
        """
        if not v or not v.strip():
            raise ValueError("span_id cannot be empty")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "control_execution_id": "550e8400-e29b-41d4-a716-446655440000",
                    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                    "span_id": "00f067aa0ba902b7",
                    "agent_uuid": "550e8400-e29b-41d4-a716-446655440001",
                    "agent_name": "my-agent",
                    "control_id": 123,
                    "control_name": "sql-injection-check",
                    "check_stage": "pre",
                    "applies_to": "llm_call",
                    "action": "deny",
                    "matched": True,
                    "confidence": 0.95,
                    "timestamp": "2025-01-09T10:30:00Z",
                    "execution_duration_ms": 15.3,
                    "evaluator_name": "regex",
                    "selector_path": "input",
                }
            ]
        }
    }


# =============================================================================
# Batch Ingestion Models
# =============================================================================


class BatchEventsRequest(BaseModel):
    """
    Request model for batch event ingestion.

    SDKs batch events and send them to the server periodically.
    This reduces HTTP overhead significantly (100x reduction).

    Attributes:
        events: List of control execution events to ingest
    """

    events: list[ControlExecutionEvent] = Field(
        ..., min_length=1, max_length=1000, description="List of events to ingest"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "events": [
                        {
                            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                            "span_id": "00f067aa0ba902b7",
                            "agent_uuid": "550e8400-e29b-41d4-a716-446655440001",
                            "agent_name": "my-agent",
                            "control_id": 123,
                            "control_name": "sql-injection-check",
                            "check_stage": "pre",
                            "applies_to": "llm_call",
                            "action": "deny",
                            "matched": True,
                            "confidence": 0.95,
                        }
                    ]
                }
            ]
        }
    }


class BatchEventsResponse(BaseModel):
    """
    Response model for batch event ingestion.

    Attributes:
        received: Number of events received
        enqueued: Number of events successfully enqueued
        dropped: Number of events dropped (queue full)
        status: Overall status ('queued', 'partial', 'failed')
    """

    received: int = Field(..., ge=0, description="Number of events received")
    enqueued: int = Field(..., ge=0, description="Number of events enqueued")
    dropped: int = Field(..., ge=0, description="Number of events dropped")
    status: Literal["queued", "partial", "failed"] = Field(
        ..., description="Overall ingestion status"
    )


# =============================================================================
# Query Models
# =============================================================================


class EventQueryRequest(BaseModel):
    """
    Request model for querying raw events.

    Supports filtering by various criteria and pagination.

    Attributes:
        trace_id: Filter by trace ID (get all events for a request)
        span_id: Filter by span ID (get all events for a function call)
        control_execution_id: Filter by specific event ID
        agent_uuid: Filter by agent UUID
        control_ids: Filter by control IDs
        actions: Filter by actions (allow, deny, warn, log)
        matched: Filter by matched status
        check_stages: Filter by check stages (pre, post)
        applies_to: Filter by call type (llm_call, tool_call)
        start_time: Filter events after this time
        end_time: Filter events before this time
        limit: Maximum number of events to return
        offset: Offset for pagination
    """

    trace_id: str | None = Field(
        default=None, description="Filter by trace ID (all events for a request)"
    )
    span_id: str | None = Field(
        default=None, description="Filter by span ID (all events for a function)"
    )
    control_execution_id: str | None = Field(
        default=None, description="Filter by specific event ID"
    )
    agent_uuid: UUID | None = Field(default=None, description="Filter by agent UUID")
    control_ids: list[int] | None = Field(
        default=None, description="Filter by control IDs"
    )
    actions: list[Literal["allow", "deny", "warn", "log"]] | None = Field(
        default=None, description="Filter by actions"
    )
    matched: bool | None = Field(default=None, description="Filter by matched status")
    check_stages: list[Literal["pre", "post"]] | None = Field(
        default=None, description="Filter by check stages"
    )
    applies_to: list[Literal["llm_call", "tool_call"]] | None = Field(
        default=None, description="Filter by call types"
    )
    start_time: datetime | None = Field(
        default=None, description="Filter events after this time"
    )
    end_time: datetime | None = Field(
        default=None, description="Filter events before this time"
    )
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum events")
    offset: int = Field(default=0, ge=0, description="Pagination offset")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"},
                {
                    "agent_uuid": "550e8400-e29b-41d4-a716-446655440001",
                    "actions": ["deny", "warn"],
                    "start_time": "2025-01-09T00:00:00Z",
                    "limit": 50,
                },
            ]
        }
    }


class EventQueryResponse(BaseModel):
    """
    Response model for event queries.

    Attributes:
        events: List of matching events
        total: Total number of matching events (for pagination)
        limit: Limit used in query
        offset: Offset used in query
    """

    events: list[ControlExecutionEvent] = Field(..., description="Matching events")
    total: int = Field(..., ge=0, description="Total matching events")
    limit: int = Field(..., description="Limit used in query")
    offset: int = Field(..., description="Offset used in query")


# =============================================================================
# Statistics Models
# =============================================================================


class ControlStats(BaseModel):
    """
    Aggregated statistics for a single control.

    Attributes:
        control_id: Database ID of the control
        control_name: Name of the control
        execution_count: Total number of executions
        match_count: Number of times the control matched
        non_match_count: Number of times the control did not match
        allow_count: Number of allow actions
        deny_count: Number of deny actions
        warn_count: Number of warn actions
        log_count: Number of log actions
        error_count: Number of errors during evaluation
        avg_confidence: Average confidence score
        avg_duration_ms: Average execution duration in milliseconds
    """

    control_id: int = Field(..., description="Control ID")
    control_name: str = Field(..., description="Control name")
    execution_count: int = Field(..., ge=0, description="Total executions")
    match_count: int = Field(..., ge=0, description="Total matches")
    non_match_count: int = Field(..., ge=0, description="Total non-matches")
    allow_count: int = Field(..., ge=0, description="Allow actions")
    deny_count: int = Field(..., ge=0, description="Deny actions")
    warn_count: int = Field(..., ge=0, description="Warn actions")
    log_count: int = Field(..., ge=0, description="Log actions")
    error_count: int = Field(..., ge=0, description="Evaluation errors")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence")
    avg_duration_ms: float | None = Field(
        default=None, ge=0, description="Average duration (ms)"
    )


class StatsRequest(BaseModel):
    """
    Request model for aggregated statistics.

    Attributes:
        agent_uuid: Agent to get stats for
        time_range: Time range (1m, 5m, 15m, 1h, 24h, 7d)
        control_id: Optional specific control to filter by
    """

    agent_uuid: UUID = Field(..., description="Agent UUID")
    time_range: Literal["1m", "5m", "15m", "1h", "24h", "7d"] = Field(
        default="5m", description="Time range"
    )
    control_id: int | None = Field(
        default=None, description="Optional control ID filter"
    )


class StatsResponse(BaseModel):
    """
    Response model for aggregated statistics.

    Invariant: total_executions = total_matches + total_non_matches + total_errors

    Matches have actions (allow, deny, warn, log) tracked in action_counts.
    sum(action_counts.values()) == total_matches

    Attributes:
        agent_uuid: Agent UUID
        time_range: Time range used
        stats: List of per-control statistics
        total_executions: Total executions across all controls
        total_matches: Total matches across all controls (evaluator matched)
        total_non_matches: Total non-matches across all controls (evaluator didn't match)
        total_errors: Total errors across all controls (evaluation failed)
        action_counts: Breakdown of actions for matched executions
    """

    agent_uuid: UUID = Field(..., description="Agent UUID")
    time_range: str = Field(..., description="Time range used")
    stats: list[ControlStats] = Field(..., description="Per-control statistics")
    total_executions: int = Field(
        ..., ge=0, description="Total executions across all controls"
    )
    total_matches: int = Field(
        default=0, ge=0, description="Total matches across all controls"
    )
    total_non_matches: int = Field(
        default=0, ge=0, description="Total non-matches across all controls"
    )
    total_errors: int = Field(
        default=0, ge=0, description="Total errors across all controls"
    )
    action_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Action breakdown for matches: {allow, deny, warn, log}",
    )
