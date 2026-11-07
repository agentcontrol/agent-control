"""Server-owned Prometheus observer for bounded Runtime stage timings."""

import time

from agent_control_models.runtime_timing import (
    Outcome,
    Stage,
    begin_request_timing,
    configure_runtime_timing,
    end_request_timing,
    observe_runtime_stage,
)
from agent_control_models.runtime_tracing import observe_runtime_interval
from prometheus_client import Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

RUNTIME_BUCKETS = (
    0.0001,
    0.00025,
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.125,
    0.15,
    0.175,
    0.2,
    0.225,
    0.25,
    0.275,
    0.3,
    0.325,
    0.35,
    0.375,
    0.4,
    0.425,
    0.45,
    0.475,
    0.5,
    0.55,
    0.6,
    0.7,
    0.8,
    1,
    1.5,
    2,
    3,
    5,
    10,
    30,
    60,
)
_STAGE_DURATION = Histogram(
    "agent_control_server_evaluation_stage_duration_seconds",
    "Inclusive Runtime stage elapsed time; nested and per-control stages are not additive",
    ("stage", "outcome"),
    buckets=RUNTIME_BUCKETS,
)


def _observe(stage: Stage, seconds: float, outcome: Outcome) -> None:
    _STAGE_DURATION.labels(stage=stage, outcome=outcome).observe(seconds)


def configure_runtime_metrics() -> None:
    """Enable timings when the server enables Prometheus metrics."""
    configure_runtime_timing(_observe)


class RuntimeTimingMiddleware:
    """Measure response serialization and total elapsed time for evaluation only."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/api/v1/evaluation":
            await self.app(scope, receive, send)
            return
        timing, token = begin_request_timing()
        started = time.perf_counter()
        outcome: Outcome = "completed"

        async def measured_send(message: Message) -> None:
            nonlocal outcome
            if message["type"] == "http.response.start":
                if message["status"] >= 400:
                    outcome = "error"
                if timing.response_ready_at is not None:
                    elapsed = time.perf_counter() - timing.response_ready_at
                    observe_runtime_stage(
                        "response_serialization",
                        elapsed,
                        outcome,
                    )
                    ended_ns = time.time_ns()
                    observe_runtime_interval(
                        "agentcontrol.stage.response_serialization",
                        ended_ns - int(elapsed * 1e9),
                        ended_ns,
                    )
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        except BaseException:
            outcome = "error"
            raise
        finally:
            observe_runtime_stage("request_total", time.perf_counter() - started, outcome)
            end_request_timing(token)
