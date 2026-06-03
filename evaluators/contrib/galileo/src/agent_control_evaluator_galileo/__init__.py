"""Agent Control Evaluator - Galileo.

This package provides Galileo evaluators for agent-control.

Available evaluators:
    - galileo.luna: Galileo Luna direct scorer evaluation

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

from agent_control_evaluator_galileo.luna import (
    LUNA_AVAILABLE,
    GalileoLunaClient,
    LunaEvaluator,
    LunaEvaluatorConfig,
    LunaOperator,
    ScorerInvokeRequest,
    ScorerInvokeResponse,
)

__all__ = [
    "GalileoLunaClient",
    "ScorerInvokeRequest",
    "ScorerInvokeResponse",
    "LunaEvaluator",
    "LunaEvaluatorConfig",
    "LunaOperator",
    "LUNA_AVAILABLE",
]
