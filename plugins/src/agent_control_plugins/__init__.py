"""Agent Control Plugins.

This package contains plugin implementations for agent-control.
Built-in plugins (regex, list) are registered automatically on import.

Available plugins:
    - regex: Regular expression matching (built-in)
    - list: List-based value matching (built-in)
    - galileo-luna2: Galileo Luna-2 runtime protection (pip install agent-control-plugins[luna2])

Custom evaluators are PluginEvaluator classes deployed with the engine.
Their schemas are registered via initAgent for validation purposes.
"""

from agent_control_models import PluginEvaluator, PluginMetadata, register_plugin

# Import built-in plugins to auto-register them
from .builtin import ListControlEvaluatorPlugin, RegexControlEvaluatorPlugin, SQLControlEvaluatorPlugin

__version__ = "0.1.0"

__all__ = [
    "PluginEvaluator",
    "PluginMetadata",
    "register_plugin",
    "RegexControlEvaluatorPlugin",
    "ListControlEvaluatorPlugin",
    "SQLControlEvaluatorPlugin",
]

