"""Agent Control Evaluators.

This package contains builtin evaluator implementations for agent-control.
Built-in evaluators (regex, list, json, sql) are registered automatically on import.

Available evaluators:
    Built-in (no namespace):
        - regex: Regular expression matching
        - list: List-based value matching
        - json: JSON validation
        - sql: SQL query validation

Naming convention:
    - Built-in: "regex", "list", "json", "sql"
    - External: "provider.name" (e.g., "galileo.luna2")
    - Agent-scoped: "agent:name" (custom code deployed with agent)

External evaluators are installed via separate packages (e.g., agent-control-evaluator-galileo).
Custom evaluators are Evaluator classes deployed with the engine.
Their schemas are registered via initAgent for validation purposes.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-evaluators")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

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
