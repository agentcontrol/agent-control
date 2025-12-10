"""Agent Control Plugins.

This package contains plugin implementations for agent-control.
Built-in plugins (regex, list) are registered automatically on import.
Custom evaluators should be registered via PUT /api/v1/evaluators.

Available plugins:
    - regex: Regular expression matching (built-in)
    - list: List-based value matching (built-in)
    - galileo-luna2: Galileo Luna-2 runtime protection (pip install agent-control-plugins[luna2])

Custom evaluators registered via /api/v1/evaluators are dynamically loaded.
"""

from agent_control_models import PluginEvaluator, PluginMetadata, register_plugin

# Import built-in plugins to auto-register them
from .builtin import ListPlugin, RegexPlugin
from .dynamic import (
    clear_caches,
    create_dynamic_evaluator_class,
    get_cache_stats,
    get_or_create_instance,
    invalidate_instances,
    register_custom_evaluator,
)

__version__ = "0.1.0"

__all__ = [
    "PluginEvaluator",
    "PluginMetadata",
    "register_plugin",
    "RegexPlugin",
    "ListPlugin",
    # Dynamic evaluator factory
    "create_dynamic_evaluator_class",
    "get_or_create_instance",
    "register_custom_evaluator",
    "invalidate_instances",
    "get_cache_stats",
    "clear_caches",
]

