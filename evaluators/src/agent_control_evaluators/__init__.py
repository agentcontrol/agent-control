"""Agent Control Evaluators.

This package contains evaluator implementations for agent-control.
Built-in evaluators (regex, list, json, sql) are registered automatically on import.

Available evaluators:
    - regex: Regular expression matching (built-in)
    - list: List-based value matching (built-in)
    - json: JSON validation (built-in)
    - sql: SQL query validation (built-in)
    - galileo-luna2: Galileo Luna-2 runtime protection (pip install agent-control-evaluators[luna2])

Custom evaluators are Evaluator classes deployed with the engine.
Their schemas are registered via initAgent for validation purposes.
"""

from agent_control_models import Evaluator, EvaluatorMetadata, register_evaluator

# Import built-in evaluators to auto-register them
from .builtin import JSONEvaluator, ListEvaluator, RegexEvaluator, SQLEvaluator

__version__ = "0.1.0"

__all__ = [
    "Evaluator",
    "EvaluatorMetadata",
    "register_evaluator",
    "RegexEvaluator",
    "ListEvaluator",
    "JSONEvaluator",
    "SQLEvaluator",
]
