"""Agent Control Engine - Rule execution logic and evaluator system."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-engine")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from agent_control_evaluators import (
    clear_evaluator_cache,
    discover_evaluators,
    ensure_evaluators_discovered,
    get_evaluator_instance,
    list_evaluators,
    reset_evaluator_discovery,
)

__all__ = [
    "clear_evaluator_cache",
    "discover_evaluators",
    "ensure_evaluators_discovered",
    "get_evaluator_instance",
    "list_evaluators",
    "reset_evaluator_discovery",
]
