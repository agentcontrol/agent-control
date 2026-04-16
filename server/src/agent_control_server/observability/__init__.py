"""Observability package for control execution tracking.

This package provides a simplified, interface-based design for observability:

- **EventIngestor**: Entry point for events (direct or custom buffered processing)
- **EventStore**: Storage backend (Postgres or custom)

The architecture is designed for flexibility:
- Swap implementations via dependency injection
- No pre-aggregation - stats computed at query time
- Simple enough for open-source adoption
- Extensible for enterprise use cases

Example:
    from agent_control_server.observability import (
        DirectEventIngestor,
        PostgresEventStore,
    )

    # Default setup
    store = PostgresEventStore(session_maker)
    ingestor = DirectEventIngestor(store)

    # Custom setup (enterprise)
    store = ClickhouseEventStore(client)  # user-provided
    ingestor = RedisEventIngestor(redis, store)  # user-provided
"""

from .ingest import DirectEventIngestor, EventIngestor, IngestResult
from .sinks import (
    ResolvedControlEventBackend,
    get_registered_control_event_sink_factory_names,
    register_control_event_sink_factory,
    resolve_control_event_backend,
    unregister_control_event_sink_factory,
)
from .store import (
    EventQuery,
    EventQueryResult,
    EventStore,
    PostgresEventStore,
    StatsResult,
)

__all__ = [
    # Ingest interfaces
    "EventIngestor",
    "IngestResult",
    "DirectEventIngestor",
    "ResolvedControlEventBackend",
    "register_control_event_sink_factory",
    "unregister_control_event_sink_factory",
    "get_registered_control_event_sink_factory_names",
    "resolve_control_event_backend",
    # Store interfaces
    "EventStore",
    "EventQuery",
    "EventQueryResult",
    "StatsResult",
    # Built-in implementations
    "PostgresEventStore",
]
