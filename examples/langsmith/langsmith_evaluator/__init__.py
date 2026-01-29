"""LangSmith evaluator for agent_control.

This module provides a LangSmith-based evaluator that can be used with
the Agent Control SDK to evaluate agent outputs using LangSmith's evaluation APIs.

Example:
    ```python
    from langsmith_evaluator import LangSmithEvaluator, LangSmithEvaluatorConfig

    config = LangSmithEvaluatorConfig(
        metric="toxicity",
        threshold=0.8,
        langsmith_project="my-project",
    )

    evaluator = LangSmithEvaluator(config)
    result = await evaluator.evaluate("some text")
    ```
"""

from .config import LangSmithEvaluatorConfig, LangSmithMetric
from .evaluator import LangSmithEvaluator

__all__ = [
    "LangSmithEvaluator",
    "LangSmithEvaluatorConfig",
    "LangSmithMetric",
]
