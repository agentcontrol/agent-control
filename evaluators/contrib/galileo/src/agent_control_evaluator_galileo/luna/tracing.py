"""Optional tracing helpers for Luna scorer evaluation."""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol


class TraceSpan(Protocol):
    """Subset of tracing span behavior used by this package."""

    def set_data(self, key: str, value: object) -> None:
        """Attach diagnostic data to the active span."""


@contextmanager
def trace_span(
    *,
    op: str,
    name: str,
    data: dict[str, object] | None = None,
) -> Iterator[TraceSpan | None]:
    """Start an optional tracing span when a tracing SDK is installed."""
    start_span = _load_start_span()
    if start_span is None:
        yield None
        return

    with start_span(op=op, name=name) as span:
        for key, value in (data or {}).items():
            span.set_data(key, value)
        yield span


@functools.lru_cache(maxsize=1)
def _load_start_span() -> Any | None:
    """Load the optional tracing span factory once per process."""
    try:
        from sentry_sdk import start_span  # type: ignore[import-not-found]
    except ImportError:
        return None
    return start_span


def set_span_data(span: TraceSpan | None, key: str, value: object) -> None:
    """Attach span data without letting tracing failures affect evaluation."""
    if span is None:
        return
    try:
        span.set_data(key, value)
    except Exception:
        pass
