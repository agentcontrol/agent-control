"""Opt-in connection-pool timing for load-test diagnostic requests."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Any

_KEY = "galileo_luna_pool_timing"
_ENABLED_ENV = "GALILEO_LUNA_HTTP_DIAGNOSTICS"
_installed = False
_lock = threading.Lock()
logger = logging.getLogger(__name__)


@dataclass
class PoolTiming:
    """Keep timing state on one diagnostic request without retaining payload data."""

    started_ns: int = field(default_factory=perf_counter_ns)
    queued_ns: int | None = None
    assigned_ns: int | None = None
    before_queue_ns: int | None = None
    queue_wait_ns: int = 0
    housekeeping_ns: int = 0
    resume_ns: int = 0

    def finish(self) -> dict[str, float | None]:
        """Return connection-pool intervals in milliseconds."""
        ended_ns = perf_counter_ns()
        if self.queued_ns is not None:
            self.queue_wait_ns += max(0, ended_ns - self.queued_ns)
            self.queued_ns = None
        return {
            "http_pool_before_queue_ms": _milliseconds(self.before_queue_ns),
            "http_pool_queue_ms": _milliseconds(self.queue_wait_ns),
            "http_pool_housekeeping_ms": _milliseconds(self.housekeeping_ns),
            "http_pool_resume_ms": _milliseconds(self.resume_ns),
        }


def _milliseconds(value_ns: int | None) -> float | None:
    return value_ns / 1_000_000 if value_ns is not None else None


def _install_hooks() -> None:
    """Observe HTTPcore's queue assignment without changing its pool decisions."""
    global _installed
    with _lock:
        if _installed:
            return
        from httpcore._async.connection_pool import AsyncPoolRequest

        original_init = AsyncPoolRequest.__init__
        original_assign = AsyncPoolRequest.assign_to_connection
        original_clear = AsyncPoolRequest.clear_connection
        original_wait = AsyncPoolRequest.wait_for_connection

        def initialize(self: Any, request: Any) -> None:
            original_init(self, request)
            timing = request.extensions.get(_KEY)
            if isinstance(timing, PoolTiming):
                now = perf_counter_ns()
                timing.before_queue_ns = max(0, now - timing.started_ns)
                timing.queued_ns = now

        def assign(self: Any, connection: Any) -> None:
            original_assign(self, connection)
            timing = self.request.extensions.get(_KEY)
            if isinstance(timing, PoolTiming):
                now = perf_counter_ns()
                if timing.queued_ns is not None:
                    timing.queue_wait_ns += max(0, now - timing.queued_ns)
                    timing.queued_ns = None
                timing.assigned_ns = now

        def clear(self: Any) -> None:
            original_clear(self)
            timing = self.request.extensions.get(_KEY)
            if isinstance(timing, PoolTiming):
                timing.queued_ns = perf_counter_ns()
                timing.assigned_ns = None

        async def wait(self: Any, timeout: float | None = None) -> Any:
            entered_ns = perf_counter_ns()
            connection = await original_wait(self, timeout=timeout)
            resumed_ns = perf_counter_ns()
            timing = self.request.extensions.get(_KEY)
            if isinstance(timing, PoolTiming) and timing.assigned_ns is not None:
                timing.housekeeping_ns += max(0, entered_ns - timing.assigned_ns)
                timing.resume_ns += max(0, resumed_ns - entered_ns)
            return connection

        # HTTPcore does not expose a public connection-pool wait hook. Keep this
        # version-sensitive adapter disabled unless explicitly enabled.
        AsyncPoolRequest.__init__ = initialize  # type: ignore[method-assign]
        AsyncPoolRequest.assign_to_connection = assign  # type: ignore[method-assign]
        AsyncPoolRequest.clear_connection = clear  # type: ignore[method-assign]
        AsyncPoolRequest.wait_for_connection = wait  # type: ignore[method-assign]
        _installed = True


def pool_diagnostics_enabled() -> bool:
    """Return whether detailed HTTP transport diagnostics were requested."""
    return os.environ.get(_ENABLED_ENV, "").lower() in {"1", "true", "enabled"}


def begin_pool_diagnostics(extensions: dict[str, Any]) -> PoolTiming | None:
    """Attach timing only to opted-in diagnostic requests."""
    if not pool_diagnostics_enabled():
        return None
    try:
        _install_hooks()
    except Exception:
        logger.warning("Luna HTTP pool diagnostics could not be installed", exc_info=True)
        return None
    timing = PoolTiming()
    extensions[_KEY] = timing
    return timing
