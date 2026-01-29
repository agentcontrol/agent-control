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

# Core infrastructure - export from _base and _registry
from agent_control_evaluators._base import Evaluator, EvaluatorConfig, EvaluatorMetadata
from agent_control_evaluators._discovery import (
    discover_evaluators,
    ensure_evaluators_discovered,
    list_evaluators,
    reset_evaluator_discovery,
)
from agent_control_evaluators._factory import clear_evaluator_cache, get_evaluator_instance
from agent_control_evaluators._registry import (
    clear_evaluators,
    get_all_evaluators,
    get_evaluator,
    register_evaluator,
)

# Import built-in evaluators to auto-register them
from agent_control_evaluators.json import JSONEvaluator, JSONEvaluatorConfig
from agent_control_evaluators.list import ListEvaluator, ListEvaluatorConfig
from agent_control_evaluators.regex import RegexEvaluator, RegexEvaluatorConfig
from agent_control_evaluators.sql import SQLEvaluator, SQLEvaluatorConfig

__version__ = "0.1.0"

__all__ = [
    # Core infrastructure
    "Evaluator",
    "EvaluatorConfig",
    "EvaluatorMetadata",
    "register_evaluator",
    "get_evaluator",
    "get_all_evaluators",
    "clear_evaluators",
    "discover_evaluators",
    "ensure_evaluators_discovered",
    "reset_evaluator_discovery",
    "list_evaluators",
    "get_evaluator_instance",
    "clear_evaluator_cache",
    # Built-in evaluators
    "RegexEvaluator",
    "RegexEvaluatorConfig",
    "ListEvaluator",
    "ListEvaluatorConfig",
    "JSONEvaluator",
    "JSONEvaluatorConfig",
    "SQLEvaluator",
    "SQLEvaluatorConfig",
]
