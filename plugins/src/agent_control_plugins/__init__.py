"""Agent Control Plugins.

This package contains plugin implementations for agent-control.
Built-in plugins (regex, list) are registered automatically on import.
Optional plugins can be installed separately.

Available plugins:
    - regex: Regular expression matching (built-in)
    - list: List-based value matching (built-in)
    - custom-code: Execute user-provided Python code (built-in)
    - galileo-luna2: Galileo Luna-2 runtime protection (pip install agent-control-plugins[luna2])
"""

from agent_control_models import PluginEvaluator, PluginMetadata, register_plugin

# Import built-in plugins to auto-register them
from .builtin import ListPlugin, RegexPlugin
from .custom_code import CustomCodePlugin

__version__ = "0.1.0"

__all__ = [
    "PluginEvaluator",
    "PluginMetadata",
    "register_plugin",
    "RegexPlugin",
    "ListPlugin",
    "CustomCodePlugin",
]

