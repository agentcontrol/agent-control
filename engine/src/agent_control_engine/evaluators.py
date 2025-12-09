"""Unified evaluator factory using plugin registry."""

import logging
from typing import Any

# Import plugins to ensure they are registered
import agent_control_plugins  # noqa: F401
from agent_control_models import EvaluatorConfig, PluginEvaluator, get_plugin

logger = logging.getLogger(__name__)


def get_evaluator(evaluator_config: EvaluatorConfig) -> PluginEvaluator[Any]:
    """Create an evaluator instance from configuration.

    All evaluators are plugins. This function:
    1. Looks up the plugin by name from the registry
    2. Creates an instance with the provided config

    Args:
        evaluator_config: The evaluator configuration with plugin name and config

    Returns:
        PluginEvaluator instance ready to use

    Raises:
        ValueError: If plugin not found
    """
    plugin_cls = get_plugin(evaluator_config.plugin)

    if plugin_cls is None:
        raise ValueError(
            f"Plugin '{evaluator_config.plugin}' not found. "
            f"Available plugins: {', '.join(get_available_plugins())}"
        )

    logger.debug(f"Creating evaluator: {evaluator_config.plugin}")
    return plugin_cls.from_dict(evaluator_config.config)


def get_available_plugins() -> list[str]:
    """Get list of available plugin names."""
    from agent_control_models import list_plugins

    return list(list_plugins().keys())
