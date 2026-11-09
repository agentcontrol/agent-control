"""Opt-in LT measurements at HTTPcore's connection-assignment boundary."""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from time import perf_counter_ns, time_ns
from typing import Any

from agent_control_models.runtime_timing import Outcome, Stage, observe_runtime_stage
from agent_control_models.runtime_tracing import observe_runtime_interval

_KEY = "galileo_pool_timing"
_installed = False
_lock = threading.Lock()


@dataclass
class PoolTiming:
    """Request-local timestamps; never stores headers, payloads, or connections."""

    started: int = field(default_factory=perf_counter_ns)
    queued: int | None = None
    assigned: int | None = None
    last_body_complete: int | None = None
    intervals: list[tuple[Stage, int, int]] = field(default_factory=list)

    def record(self, stage: Stage, start: int, end: int) -> None:
        if len(self.intervals) < 64:
            self.intervals.append((stage, start, max(start, end)))

    def finish(self, outcome: Outcome) -> None:
        ended = perf_counter_ns()
        if self.queued is not None and self.assigned is None:
            self.record("luna_pool_queue", self.queued, ended)
        if self.last_body_complete is not None:
            self.record("luna_after_receive", self.last_body_complete, ended)
        wall_end = time_ns()
        for stage, start, end in self.intervals:
            observe_runtime_stage(stage, (end - start) / 1e9, outcome)
            observe_runtime_interval(
                "agentcontrol.transport." + stage.removeprefix("luna_"),
                wall_end - (ended - start),
                wall_end - (ended - end),
            )


def _install_hooks() -> None:
    """Keep HTTPcore's timeout, assignment, release and cancellation logic intact.

    HTTPcore 1.0 has no public pool-wait trace event. The LT-only adapter adds
    timestamps around its existing methods and ignores untagged requests.
    """
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
                timing.record("luna_before_pool", timing.started, now)
                timing.queued = now

        def assign(self: Any, connection: Any) -> None:
            original_assign(self, connection)
            timing = self.request.extensions.get(_KEY)
            if isinstance(timing, PoolTiming):
                now = perf_counter_ns()
                timing.assigned = now
                if timing.queued is not None:
                    timing.record("luna_pool_queue", timing.queued, now)

        def clear(self: Any) -> None:
            original_clear(self)
            timing = self.request.extensions.get(_KEY)
            if isinstance(timing, PoolTiming):
                timing.queued = perf_counter_ns()
                timing.assigned = None

        async def wait(self: Any, timeout: float | None = None) -> Any:
            entered = perf_counter_ns()
            connection = await original_wait(self, timeout=timeout)
            resumed = perf_counter_ns()
            timing = self.request.extensions.get(_KEY)
            if isinstance(timing, PoolTiming) and timing.assigned is not None:
                timing.record("luna_pool_housekeeping", timing.assigned, entered)
                timing.record("luna_pool_resume", max(timing.assigned, entered), resumed)
            return connection

        # The private boundary is confined to these four wrappers, tested on 1.0.9.
        AsyncPoolRequest.__init__ = initialize  # type: ignore[method-assign]
        AsyncPoolRequest.assign_to_connection = assign  # type: ignore[method-assign]
        AsyncPoolRequest.clear_connection = clear  # type: ignore[method-assign]
        AsyncPoolRequest.wait_for_connection = wait  # type: ignore[method-assign]
        _installed = True


def begin_pool_diagnostics(extensions: dict[str, Any]) -> PoolTiming | None:
    """Tag only opted-in Luna requests, leaving normal client behavior unchanged."""
    if os.environ.get("GALILEO_LUNA_HTTP_DIAGNOSTICS", "").lower() not in {"true", "1"}:
        return None
    _install_hooks()
    timing = PoolTiming()
    extensions[_KEY] = timing
    return timing


def diagnostic_outcome(error: BaseException | None) -> Outcome:
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    return "error" if error is not None else "completed"
