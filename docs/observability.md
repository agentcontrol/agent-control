# Observability

Real-time monitoring and analytics for control executions.

Agent Control's observability system provides visibility into how your controls are performing — execution counts, match rates, action distributions, and errors. Built on a simple interface-based design, it's easy to understand, test, and extend.

---

## What You Get: Stats Hierarchy

Every control evaluation produces stats organized in a clear hierarchy:

```
                    Executions
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
     Matches       Non-Matches       Errors
        │
        ├── Allow
        ├── Deny
        ├── Warn
        └── Log
```

**Key Invariant:** `Executions = Matches + Non-Matches + Errors` (mutually exclusive)

| Metric | Description |
|--------|-------------|
| `execution_count` | Total control evaluations |
| `match_count` | Controls where condition matched |
| `non_match_count` | Controls evaluated but didn't match |
| `error_count` | Controls that failed during evaluation |
| `action_counts` | Action breakdown for matches: `{allow, deny, warn, log}` |

---

## Architecture Overview

The observability system uses a simple **interface-based design** with two swappable abstractions:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            EVENT SOURCES                                    │
│                                                                             │
│   ┌─────────────┐              ┌─────────────┐                              │
│   │    SDK      │              │   Server    │                              │
│   │  (local     │              │  (remote    │                              │
│   │  controls)  │              │  controls)  │                              │
│   └──────┬──────┘              └──────┬──────┘                              │
│          │                            │                                     │
│          │    HTTP POST               │    Direct call                      │
│          └───────────┬────────────────┘                                     │
│                      ▼                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  EventIngestor (Protocol)                   │
│                                                             │
│  Built-in:                   User-provided:                 │
│  ┌─────────────────────┐     ┌─────────────────────┐        │
│  │ DirectEventIngestor │     │ QueuedEventIngestor │        │
│  │ (sync processing)   │     │ (asyncio.Queue)     │        │
│  └─────────────────────┘     ├─────────────────────┤        │
│                              │ KafkaEventIngestor  │        │
│                              ├─────────────────────┤        │
│                              │ RabbitMQIngestor    │        │
│                              ├─────────────────────┤        │
│                              │ RedisEventIngestor  │        │
│                              └─────────────────────┘        │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      EventStore (ABC)                       │
│                                                             │
│  Built-in:                   User-provided:                 │
│  ┌─────────────────────┐     ┌─────────────────────┐        │
│  │ PostgresEventStore  │     │ ClickhouseEventStore│        │
│  │ (JSONB + indexes)   │     │ (columnar, fast)    │        │
│  └─────────────────────┘     ├─────────────────────┤        │
│                              │ TimescaleDBStore    │        │
│                              │ (time-series)       │        │
│                              └─────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Principles:**

1. **Interface-based** — `EventIngestor` and `EventStore` are swappable
2. **Simple flow** — Events go directly from source to storage
3. **Query-time aggregation** — No pre-computed buckets, stats computed on demand
4. **JSONB storage** — Flexible schema, no migrations for new fields

### EventIngestor (Protocol)

Entry point for all observability events:

```python
from typing import Protocol

class EventIngestor(Protocol):
    async def ingest(self, events: list[ControlExecutionEvent]) -> IngestResult:
        """Ingest events. Returns counts of received/processed/dropped."""
        ...

    async def flush(self) -> None:
        """Flush any buffered events (for graceful shutdown)."""
        ...
```

### EventStore (ABC)

Storage backend abstraction:

```python
from abc import ABC, abstractmethod

class EventStore(ABC):
    @abstractmethod
    async def store(self, events: list[ControlExecutionEvent]) -> int:
        """Store raw events. Returns count stored."""
        pass

    @abstractmethod
    async def query_stats(
        self, agent_uuid: UUID, time_range: timedelta, control_id: int | None = None
    ) -> StatsResult:
        """Query stats (aggregated at query time)."""
        pass

    @abstractmethod
    async def query_events(self, query: EventQueryRequest) -> EventQueryResponse:
        """Query raw events with filters and pagination."""
        pass
```

### Wiring It Up

```python
# Default configuration (simple)
store = PostgresEventStore(session_maker)
ingestor = DirectEventIngestor(store)

# Custom configuration (e.g., Clickhouse for high volume)
store = ClickhouseEventStore(client)  # You implement this
ingestor = DirectEventIngestor(store)
```

---

## Components

### 1. ID Generation

Every observability event needs three IDs for correlation:

| ID | Format | Generated By | Purpose |
|----|--------|--------------|---------|
| `trace_id` | 128-bit hex (32 chars) | SDK | Groups all events in a request |
| `span_id` | 64-bit hex (16 chars) | SDK | Identifies a single `@control` call |
| `control_execution_id` | UUID v4 | Engine | Identifies a single control evaluation |

**Trace & Span IDs (SDK)**

Generated in the SDK when `@control` decorator runs. OpenTelemetry-compatible — if OTEL is active, IDs are extracted from current context:

```python
from agent_control import get_trace_and_span_ids, with_trace

# Auto-detect from OpenTelemetry context (if available)
trace_id, span_id = get_trace_and_span_ids()

# Or use explicit scoping
with with_trace() as (trace_id, span_id):
    result = await my_agent.process(input)
```

**Control Execution ID (Engine)**

Generated by the engine at the moment a control is evaluated. Since the same engine runs both locally (SDK) and remotely (Server), ID generation is **uniform** regardless of where the control executes.

### 2. Event Batching (SDK)

The SDK batches events before sending to reduce network overhead:

```python
# Configuration (environment variables)
AGENT_CONTROL_BATCH_SIZE=100        # Max events per batch
AGENT_CONTROL_FLUSH_INTERVAL=10.0   # Seconds between flushes
```

Events are sent when **either** condition is met (whichever comes first).

```python
import agent_control

# Initialize with observability enabled
agent_control.init(
    agent_name="my-agent",
    observability_enabled=True,  # Enable event collection
)

# Events are automatically batched and sent
@agent_control.control()
async def chat(message: str) -> str:
    return await llm.complete(message)
```

---

## Data Model

### Database Schema (Simplified)

Events are stored with minimal indexed columns + JSONB for flexibility:

```sql
CREATE TABLE control_execution_events (
    control_execution_id VARCHAR(36) PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    agent_uuid UUID NOT NULL,
    data JSONB NOT NULL  -- Full event stored here
);

-- Primary index for time-range queries per agent
CREATE INDEX ix_events_agent_time ON control_execution_events (agent_uuid, timestamp DESC);

-- Expression index for grouping by control
CREATE INDEX ix_events_data_control_id ON control_execution_events ((data->>'control_id'));
```

**Why JSONB?**
- No migrations needed for new event fields
- Flexible querying via expression indexes
- Full event data preserved for debugging

### Control Execution Event

Each control evaluation produces an event (stored in the `data` JSONB column):

```typescript
{
  control_execution_id: string,  // Unique ID (for correlation)
  trace_id: string,              // OpenTelemetry trace ID (32 hex chars)
  span_id: string,               // OpenTelemetry span ID (16 hex chars)
  agent_uuid: UUID,
  agent_name: string,
  control_id: number,
  control_name: string,
  check_stage: "pre" | "post",
  applies_to: "llm_call" | "tool_call",
  action: "allow" | "deny" | "warn" | "log",
  matched: boolean,
  confidence: number,            // 0.0 - 1.0
  timestamp: datetime,
  error_message?: string,
  metadata: object
}
```

---

## API Endpoints

All observability endpoints are under `/api/v1/observability/`.

### Quick Reference

| Use Case | Endpoint | Parameters | Returns |
|----------|----------|------------|---------|
| **Health check** | `GET /status` | — | System status |
| **Ingest events** | `POST /events` | `events[]` in body | Ingestion result |
| **Agent overview** | `GET /stats` | `agent_uuid`, `time_range` | `totals` + `controls[]` |
| **Agent trends** | `GET /stats` | + `include_timeseries=true` | `totals.timeseries[]` included |
| **Control stats** | `GET /stats/controls/{id}` | `agent_uuid`, `time_range` | `control_id`, `control_name`, `stats` |
| **Control trends** | `GET /stats/controls/{id}` | + `include_timeseries=true` | `stats.timeseries[]` included |
| **Query raw events** | `POST /events/query` | Filters in body | `events[]` with pagination |

**Response Structures:**
- **Agent stats** (`GET /stats`): `totals` (agent-level) + `controls[]` (per-control breakdown)
- **Control stats** (`GET /stats/controls/{id}`): `control_id`, `control_name`, `stats` (control-level)

---

### 1. Status (Health Check)

Check observability system health.

```http
GET /api/v1/observability/status
```

**Example Request:**
```bash
curl "http://localhost:8000/api/v1/observability/status"
```

**Example Response:**
```json
{
    "status": "ok",
    "ingestor_initialized": true,
    "store_initialized": true
}
```

### 2. Ingest Events

Ingest batched control execution events from the SDK.

```http
POST /api/v1/observability/events
Content-Type: application/json
```

**Request Body:**
```json
{
  "events": [
    {
      "control_execution_id": "...",
      "trace_id": "...",
      "span_id": "...",
      "agent_uuid": "...",
      "control_id": 1,
      "control_name": "block-toxic",
      "matched": true,
      "action": "deny",
      "confidence": 0.95,
      "timestamp": "2026-01-20T12:00:00Z"
    }
  ]
}
```

**Response:** `202 Accepted`
```json
{
  "received": 100,
  "enqueued": 100,
  "dropped": 0,
  "status": "queued"
}
```

### 3. Get Agent Stats

Get agent-level aggregated statistics with per-control breakdown.

```http
GET /api/v1/observability/stats?agent_uuid=<uuid>&time_range=<range>&include_timeseries=<bool>
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_uuid` | UUID | Yes | Agent to get stats for |
| `time_range` | string | No | Time range: `1m`, `5m`, `15m`, `1h`, `24h`, `7d`, `30d`, `180d`, `365d` (default: `5m`) |
| `include_timeseries` | boolean | No | Include time-series data for trend visualization (default: `false`) |

**Time-Series Bucket Sizes:**

When `include_timeseries=true`, data is bucketed automatically based on the time range:

| Time Range | Bucket Size | Data Points |
|------------|-------------|-------------|
| `1m` | 10 seconds | ~6 |
| `5m` | 30 seconds | ~10 |
| `15m` | 1 minute | ~15 |
| `1h` | 5 minutes | ~12 |
| `24h` | 1 hour | ~24 |
| `7d` | 6 hours | ~28 |
| `30d` | 1 day | ~30 |
| `180d` | 7 days | ~26 |
| `365d` | 30 days | ~12 |

**Example Request:**
```bash
curl "http://localhost:8000/api/v1/observability/stats?agent_uuid=563de065-23aa-5d75-b594-cfa73abcc53c&time_range=1h"
```

**Example Response:**
```json
{
    "agent_uuid": "563de065-23aa-5d75-b594-cfa73abcc53c",
    "time_range": "1h",
    "totals": {
        "execution_count": 8,
        "match_count": 7,
        "non_match_count": 1,
        "error_count": 0,
        "action_counts": {
            "allow": 3,
            "deny": 2,
            "warn": 1,
            "log": 1
        },
        "timeseries": null
    },
    "controls": [
        {
            "control_id": 1,
            "control_name": "block-prompt-injection",
            "execution_count": 5,
            "match_count": 4,
            "non_match_count": 1,
            "allow_count": 3,
            "deny_count": 0,
            "warn_count": 0,
            "log_count": 1,
            "error_count": 0,
            "avg_confidence": 0.95,
            "avg_duration_ms": 11.4
        },
        {
            "control_id": 2,
            "control_name": "block-credit-card",
            "execution_count": 3,
            "match_count": 3,
            "non_match_count": 0,
            "allow_count": 0,
            "deny_count": 2,
            "warn_count": 1,
            "log_count": 0,
            "error_count": 0,
            "avg_confidence": 0.95,
            "avg_duration_ms": 13.3
        }
    ]
}
```

**Response Structure:**

| Field | Description |
|-------|-------------|
| `totals` | Agent-level aggregate statistics (includes timeseries when requested) |
| `controls` | Per-control breakdown for discovery and drilling down |

**Example Request with Time-Series:**
```bash
curl "http://localhost:8000/api/v1/observability/stats?agent_uuid=563de065-23aa-5d75-b594-cfa73abcc53c&time_range=1h&include_timeseries=true"
```

**Example Response with Time-Series:**
```json
{
    "agent_uuid": "563de065-23aa-5d75-b594-cfa73abcc53c",
    "time_range": "1h",
    "totals": {
        "execution_count": 8,
        "match_count": 7,
        "non_match_count": 1,
        "error_count": 0,
        "action_counts": {
            "allow": 3,
            "deny": 2,
            "warn": 1,
            "log": 1
        },
        "timeseries": [
            {
                "timestamp": "2026-01-30T17:10:00Z",
                "execution_count": 0,
                "match_count": 0,
                "non_match_count": 0,
                "error_count": 0,
                "action_counts": {},
                "avg_confidence": null,
                "avg_duration_ms": null
            },
            {
                "timestamp": "2026-01-30T17:15:00Z",
                "execution_count": 2,
                "match_count": 2,
                "non_match_count": 0,
                "error_count": 0,
                "action_counts": {
                    "allow": 1,
                    "deny": 1
                },
                "avg_confidence": 0.95,
                "avg_duration_ms": 10.4
            },
            ...
        ]
    },
    "controls": [ ... ]
}
```

**Time-Series Bucket Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | datetime | Start time of the bucket (UTC) |
| `execution_count` | integer | Total executions in this bucket |
| `match_count` | integer | Matches in this bucket |
| `non_match_count` | integer | Non-matches in this bucket |
| `error_count` | integer | Errors in this bucket |
| `action_counts` | object | Action breakdown: `{allow, deny, warn, log}` |
| `avg_confidence` | float\|null | Average confidence (null if no executions) |
| `avg_duration_ms` | float\|null | Average duration in ms (null if no data) |

Empty buckets are included with zero counts and `null` averages to ensure consistent data points for charting.

### 4. Get Control Stats

Get statistics for a single control.

```http
GET /api/v1/observability/stats/controls/{control_id}?agent_uuid=<uuid>&time_range=<range>&include_timeseries=<bool>
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `control_id` | integer | Yes | Control ID to get stats for |

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_uuid` | UUID | Yes | Agent to get stats for |
| `time_range` | string | No | Time range: `1m`, `5m`, `15m`, `1h`, `24h`, `7d`, `30d`, `180d`, `365d` (default: `5m`) |
| `include_timeseries` | boolean | No | Include time-series data for trend visualization (default: `false`) |

**Example Request:**
```bash
curl "http://localhost:8000/api/v1/observability/stats/controls/1?agent_uuid=563de065-23aa-5d75-b594-cfa73abcc53c&time_range=1h&include_timeseries=true"
```

**Example Response:**
```json
{
    "agent_uuid": "563de065-23aa-5d75-b594-cfa73abcc53c",
    "time_range": "1h",
    "control_id": 1,
    "control_name": "block-prompt-injection",
    "stats": {
        "execution_count": 3,
        "match_count": 3,
        "non_match_count": 0,
        "error_count": 0,
        "action_counts": {
            "allow": 2,
            "deny": 1
        },
        "timeseries": [
            {
                "timestamp": "2026-01-30T17:30:00Z",
                "execution_count": 1,
                "match_count": 1,
                "non_match_count": 0,
                "error_count": 0,
                "action_counts": {"allow": 1},
                "avg_confidence": 0.95,
                "avg_duration_ms": 12.5
            },
            {
                "timestamp": "2026-01-30T17:35:00Z",
                "execution_count": 0,
                "match_count": 0,
                "non_match_count": 0,
                "error_count": 0,
                "action_counts": {},
                "avg_confidence": null,
                "avg_duration_ms": null
            },
            ...
        ]
    }
}
```

Note: The `controls` array is not present in control-level responses since you're already querying a specific control.

### 5. Query Events (Raw Events)

Query raw control execution events with filtering and pagination.

```http
POST /api/v1/observability/events/query
Content-Type: application/json
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trace_id` | string | No | Filter by trace ID |
| `span_id` | string | No | Filter by span ID |
| `control_execution_id` | string | No | Get specific event |
| `agent_uuid` | UUID | No | Filter by agent |
| `control_ids` | integer[] | No | Filter by control IDs |
| `actions` | string[] | No | Filter by actions: `allow`, `deny`, `warn`, `log` |
| `matched` | boolean | No | Filter by matched status |
| `check_stages` | string[] | No | Filter by check stage: `pre`, `post` |
| `applies_to` | string | No | Filter by call type: `llm_call`, `tool_call` |
| `start_time` | datetime | No | Start of time range (ISO 8601) |
| `end_time` | datetime | No | End of time range (ISO 8601) |
| `limit` | integer | No | Max results (default: 100) |
| `offset` | integer | No | Pagination offset (default: 0) |

**Example Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/observability/events/query" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_uuid": "563de065-23aa-5d75-b594-cfa73abcc53c",
    "matched": true,
    "limit": 5
  }'
```

**Example Response:**
```json
{
    "events": [
        {
            "control_execution_id": "92df0332-170c-4bc6-aefd-ab50be311062",
            "trace_id": "5848335875e1d7269e148170ccb617ca",
            "span_id": "c25549deddcaecbe",
            "agent_uuid": "563de065-23aa-5d75-b594-cfa73abcc53c",
            "agent_name": "Customer Support Agent",
            "control_id": 3,
            "control_name": "block-credit-card",
            "check_stage": "pre",
            "applies_to": "llm_call",
            "action": "deny",
            "matched": true,
            "confidence": 1.0,
            "timestamp": "2026-01-20T16:04:59.004038Z",
            "execution_duration_ms": null,
            "evaluator": "regex",
            "selector_path": null,
            "error_message": null,
            "metadata": {
                "pattern": "\\b\\d{4}[-\\s]?\\d{4}[-\\s]?\\d{4}[-\\s]?\\d{4}\\b"
            }
        }
    ],
    "total": 1,
    "limit": 5,
    "offset": 0
}
```

---

## Configuration

### Environment Variables

```bash
# SDK Configuration
AGENT_CONTROL_OBSERVABILITY_ENABLED=true   # Enable observability
AGENT_CONTROL_BATCH_SIZE=100               # Events per batch
AGENT_CONTROL_FLUSH_INTERVAL=10.0          # Seconds between flushes

# Logging Configuration
AGENT_CONTROL_LOG_ENABLED=true             # Master switch
AGENT_CONTROL_LOG_SPAN_START=true          # Log span start
AGENT_CONTROL_LOG_SPAN_END=true            # Log span end
AGENT_CONTROL_LOG_CONTROL_EVAL=true        # Log per-control evaluation
```

### Programmatic Configuration

```python
import agent_control

agent_control.init(
    agent_name="my-agent",
    observability_enabled=True,
    log_config={
        "enabled": True,
        "span_start": True,
        "span_end": True,
        "control_eval": False,  # Disable verbose per-control logs
    },
)
```

---

## Performance Characteristics

### Query-Time Aggregation

Stats are computed at query time from raw events. This is simple and works well for moderate volumes.

**Note:** The following are rough estimates based on typical PostgreSQL JSONB performance, not verified benchmarks. Actual performance depends on hardware, indexes, and query patterns.

| Query Window | Event Count | Estimated Time |
|--------------|-------------|----------------|
| 5 minutes | ~1K-10K | ~10-50ms |
| 1 hour | ~10K-100K | ~50-200ms |
| 24 hours | ~100K-1M | ~200ms-2s |

### Scaling Options

If query-time aggregation becomes a bottleneck:

1. **Add expression indexes** on frequently filtered JSONB fields
2. **Create materialized views** for heavy queries
3. **Switch to Clickhouse** — native JSON + columnar storage = fast aggregation
4. **Use TimescaleDB** — time-series optimized PostgreSQL extension

