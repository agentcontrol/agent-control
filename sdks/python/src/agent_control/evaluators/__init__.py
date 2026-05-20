"""Evaluator system for agent_control.

This module provides an evaluator architecture for extending agent_control
with external evaluation systems like Galileo Luna-2, Guardrails AI, etc.

Evaluator Discovery:
    Call `discover_evaluators()` at startup to load evaluators. This loads:
    - Built-in evaluators (regex, list, json, sql) from agent_control_evaluators
    - Third-party evaluators via the 'agent_control.evaluators' entry point group

    Then use `list_evaluators()` to get available evaluators.

Galileo evaluators:
    When installed with galileo extras, the Galileo evaluator types are available:
    ```python
    from agent_control.evaluators import LunaEvaluator, LunaEvaluatorConfig  # if galileo installed
    from agent_control.evaluators import Luna2Evaluator, Luna2EvaluatorConfig  # if luna2 installed
    ```
"""

from agent_control_engine import (
    discover_evaluators,
    ensure_evaluators_discovered,
    list_evaluators,
)
from agent_control_evaluators import register_evaluator

from .base import Evaluator, EvaluatorMetadata

__all__ = [
    "Evaluator",
    "EvaluatorMetadata",
    "discover_evaluators",
    "ensure_evaluators_discovered",
    "list_evaluators",
    "register_evaluator",
]

# Optionally export Luna-2 types when available
try:
    from agent_control_evaluator_galileo.luna import (  # type: ignore[import-not-found]  # noqa: F401
        LUNA_AVAILABLE,
        GalileoLunaClient,
        LunaEvaluator,
        LunaEvaluatorConfig,
        LunaOperator,
        ScorerInvokeInputs,
        ScorerInvokeRequest,
        ScorerInvokeResponse,
    )

    __all__.extend(
        [
            "GalileoLunaClient",
            "ScorerInvokeInputs",
            "ScorerInvokeRequest",
            "ScorerInvokeResponse",
            "LunaEvaluator",
            "LunaEvaluatorConfig",
            "LunaOperator",
            "LUNA_AVAILABLE",
        ]
    )
except ImportError:
    pass

try:
    from agent_control_evaluator_galileo.luna2 import (  # type: ignore[import-not-found]  # noqa: F401
        LUNA2_AVAILABLE,
        Luna2Evaluator,
        Luna2EvaluatorConfig,
        Luna2Metric,
        Luna2Operator,
    )

    __all__.extend(
        [
            "Luna2Evaluator",
            "Luna2EvaluatorConfig",
            "Luna2Metric",
            "Luna2Operator",
            "LUNA2_AVAILABLE",
        ]
    )
except ImportError:
    pass
