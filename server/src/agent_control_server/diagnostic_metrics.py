"""Bounded numeric-only timers for the opt-in lookup diagnostic."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

from prometheus_client import Counter, Histogram

Mode = Literal["off", "on"]
Stage = Literal[
    "authorization",
    "pool_acquire",
    "agent_query",
    "effective_query",
    "parse",
    "redis_get",
    "redis_set",
    "cache_encode",
    "cache_decode",
    "control_load",
    "engine",
    "handler",
]
_active_mode: ContextVar[Mode | None] = ContextVar("lookup_diagnostic_mode", default=None)
_DURATION = Histogram(
    "agent_control_lookup_diagnostic_seconds",
    "Diagnostic stage elapsed seconds",
    ["mode", "stage"],
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
_EVENTS = Counter(
    "agent_control_lookup_diagnostic_events", "Diagnostic cache outcomes", ["mode", "outcome"]
)
_SQL = Counter(
    "agent_control_lookup_diagnostic_sql", "Control-loader SQL execute calls", ["mode", "query"]
)


@contextmanager
def measured(stage: Stage) -> Iterator[None]:
    """Record a bounded-label duration only inside an opted-in diagnostic request."""
    mode = _active_mode.get()
    if mode is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        if mode is not None:
            _DURATION.labels(mode, stage).observe(time.perf_counter() - started)


def count_query(query: Literal["agent", "effective"]) -> None:
    mode = _active_mode.get()
    if mode is not None:
        _SQL.labels(mode, query).inc()


# Publish explicit zeros for bounded counter labels. An absent fallback series
# must not be reported as zero merely because no error was observed.
for _mode in ("off", "on"):
    for _outcome in (
        "bypass",
        "hit",
        "miss",
        "redis_read_fallback",
        "redis_write_fallback",
        "oversize_fallback",
        "fixture_mismatch",
        "fixture_write_rejected",
    ):
        _EVENTS.labels(_mode, _outcome)
    for _query in ("agent", "effective"):
        _SQL.labels(_mode, _query)
