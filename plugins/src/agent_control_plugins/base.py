"""Base classes for agent-control plugins.

Re-exports from agent_control_models for backward compatibility.
"""

from agent_control_models import PluginEvaluator, PluginMetadata, register_plugin

__all__ = ["PluginEvaluator", "PluginMetadata", "register_plugin"]

