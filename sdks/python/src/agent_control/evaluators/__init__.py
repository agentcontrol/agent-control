"""Evaluator system for agent_control.

This module provides an evaluator architecture for extending agent_control
with external evaluation systems like Galileo Luna, Galileo LLM, Guardrails AI, etc.

Evaluator Discovery:
    Call `discover_evaluators()` at startup to load evaluators. This loads:
    - Built-in evaluators (regex, list, json, sql) from agent_control_evaluators
    - Third-party evaluators via the 'agent_control.evaluators' entry point group

    Then use `list_evaluators()` to get available evaluators.

Galileo evaluators:
    When installed with galileo extras, the Galileo evaluator types are available:
    ```python
    from agent_control.evaluators import LunaEvaluator, LunaEvaluatorConfig  # if galileo installed
    from agent_control.evaluators import LlmEvaluator, LlmEvaluatorConfig    # if galileo installed
    ```

    Note: ``galileo.llm`` requires ``GALILEO_FEATURE_FLAG_LLM_EVALUATOR=enabled`` to be set.
    The evaluator is unavailable (``is_available()`` returns ``False``) until this flag is present,
    as it depends on Orbit-side support for ``execution_context`` to fetch LLM credentials.
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

# Optionally export Luna types when available
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

# Optionally export LLM evaluator types when available
try:
    from agent_control_evaluator_galileo.llm import (  # type: ignore[import-not-found]  # noqa: F401
        LLM_AVAILABLE,
        GalileoLLMClient,
        LlmEvaluator,
        LlmEvaluatorConfig,
        LlmOperator,
    )

    __all__.extend(
        [
            "GalileoLLMClient",
            "LlmEvaluator",
            "LlmEvaluatorConfig",
            "LlmOperator",
            "LLM_AVAILABLE",
        ]
    )
except ImportError:
    pass
