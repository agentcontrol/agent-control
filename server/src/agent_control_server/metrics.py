"""Prometheus metrics owned by the Agent Control server."""

from agent_control_engine.core import ControlObserverOutcome, EvaluatorObserverOutcome
from prometheus_client import Histogram

_EVALUATION_STAGE_DURATION = Histogram(
    "agent_control_server_evaluation_stage_duration_seconds",
    "Duration of evaluation endpoint stages.",
    ("stage", "outcome"),
)
_EVALUATOR_QUEUE_DURATION = Histogram(
    "agent_control_server_engine_evaluator_queue_duration_seconds",
    "Time evaluator leaves spend waiting for engine concurrency.",
    ("evaluator",),
)
_EVALUATOR_DURATION = Histogram(
    "agent_control_server_engine_evaluator_duration_seconds",
    "Time spent executing evaluator leaves.",
    ("evaluator", "outcome"),
)
_CONTROL_DURATION = Histogram(
    "agent_control_server_engine_control_duration_seconds",
    "Time spent evaluating top-level controls.",
    ("action", "outcome"),
)


def observe_evaluation_stage(
    *,
    stage: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    """Record evaluation endpoint stage duration."""
    _EVALUATION_STAGE_DURATION.labels(stage=stage, outcome=outcome).observe(duration_seconds)


class PrometheusEvaluationObserver:
    """Records engine timing observations as Prometheus histograms."""

    def observe_evaluator_queue_duration(
        self,
        *,
        evaluator_name: str,
        duration_seconds: float,
    ) -> None:
        """Record time spent waiting for evaluator concurrency."""
        _EVALUATOR_QUEUE_DURATION.labels(evaluator=evaluator_name).observe(duration_seconds)

    def observe_evaluator_duration(
        self,
        *,
        evaluator_name: str,
        outcome: EvaluatorObserverOutcome,
        duration_seconds: float,
    ) -> None:
        """Record time spent executing an evaluator."""
        _EVALUATOR_DURATION.labels(
            evaluator=evaluator_name,
            outcome=outcome,
        ).observe(duration_seconds)

    def observe_control_duration(
        self,
        *,
        action: str,
        outcome: ControlObserverOutcome,
        duration_seconds: float,
    ) -> None:
        """Record time spent evaluating a top-level control."""
        _CONTROL_DURATION.labels(action=action, outcome=outcome).observe(duration_seconds)


prometheus_evaluation_observer = PrometheusEvaluationObserver()
