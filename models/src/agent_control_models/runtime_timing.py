"""Optional bounded Runtime timings shared by server, engine and evaluators."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

Stage = Literal[
    "auth_context",
    "authorization",
    "controls_load",
    "cache_redis",
    "cache_decode",
    "engine",
    "selector",
    "evaluator_queue",
    "evaluator",
    "response_prepare",
    "luna_payload",
    "luna_client_acquire",
    "luna_http",
    "luna_decode",
    "request_validation",
    "response_serialization",
    "request_total",
    "luna_connect",
    "luna_tls",
    "luna_send",
    "luna_response_headers",
    "luna_read",
]
Outcome = Literal["completed", "error", "cancelled"]
Observer = Callable[[Stage, float, Outcome], None]
_observer: Observer | None = None
_logger = logging.getLogger(__name__)


@dataclass
class RequestTiming:
    authorized_at: float | None = None
    response_ready_at: float | None = None


_request_timing: ContextVar[RequestTiming | None] = ContextVar("ac_request_timing", default=None)


def begin_request_timing() -> tuple[RequestTiming, Token[RequestTiming | None]]:
    """Bind shared milestones to one request, including child async tasks."""
    timing = RequestTiming()
    return timing, _request_timing.set(timing)


def end_request_timing(token: Token[RequestTiming | None]) -> None:
    _request_timing.reset(token)


def mark_authorized() -> None:
    timing = _request_timing.get()
    if timing is not None:
        timing.authorized_at = time.perf_counter()


def observe_request_validation() -> None:
    timing = _request_timing.get()
    if timing is not None and timing.authorized_at is not None:
        observe_runtime_stage("request_validation", time.perf_counter() - timing.authorized_at)


def mark_response_ready() -> None:
    timing = _request_timing.get()
    if timing is not None:
        timing.response_ready_at = time.perf_counter()


def configure_runtime_timing(observer: Observer | None) -> None:
    """Install a process-local observer. Libraries otherwise perform no timing."""
    global _observer
    _observer = observer


def observe_runtime_stage(stage: Stage, seconds: float, outcome: Outcome = "completed") -> None:
    """Emit a bounded stage without changing application failure behavior."""
    if _observer is not None:
        try:
            _observer(stage, max(0.0, seconds), outcome)
        except Exception:
            _logger.debug("Runtime timing observer failed", exc_info=True)


@contextmanager
def runtime_stage(stage: Stage) -> Iterator[None]:
    """Measure inclusive elapsed time, including errors and cancellation."""
    if _observer is None:
        yield
        return
    started = time.perf_counter()
    outcome: Outcome = "completed"
    try:
        yield
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        observe_runtime_stage(stage, time.perf_counter() - started, outcome)
