"""Event storage layer for observability.

This module provides the EventStore ABC and implementations
for storing and querying control execution events.
"""

from .base import EventQuery, EventQueryResult, EventStore, StatsResult, get_bucket_size
from .postgres import PostgresEventStore

__all__ = [
    "EventStore",
    "EventQuery",
    "EventQueryResult",
    "StatsResult",
    "PostgresEventStore",
    "get_bucket_size",
]
