"""Agent Control Evaluator - Galileo.

This package provides Galileo evaluators for agent-control.

Available evaluators:
    - galileo.luna2: Galileo Luna-2 runtime protection

Installation:
    pip install agent-control-evaluator-galileo

Or via the agent-control-evaluators convenience extra:
    pip install agent-control-evaluators[galileo]
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-evaluator-galileo")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from agent_control_evaluator_galileo.luna2 import (
    LUNA2_AVAILABLE,
    Luna2Evaluator,
    Luna2EvaluatorConfig,
    Luna2Metric,
    Luna2Operator,
)

__all__ = [
    "Luna2Evaluator",
    "Luna2EvaluatorConfig",
    "Luna2Metric",
    "Luna2Operator",
    "LUNA2_AVAILABLE",
]
