"""Unified evaluator factory using plugin registry with caching."""

import json
import logging
import os
from collections import OrderedDict
from typing import Any

# Import plugins to ensure they are registered
import agent_control_plugins  # noqa: F401
from agent_control_models import EvaluatorConfig, PluginEvaluator, get_plugin

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_CACHE_SIZE = 100
EVALUATOR_CACHE_SIZE = int(os.environ.get("EVALUATOR_CACHE_SIZE", DEFAULT_CACHE_SIZE))

# LRU cache for evaluator instances: cache_key -> PluginEvaluator instance
_EVALUATOR_CACHE: OrderedDict[str, PluginEvaluator[Any]] = OrderedDict()


def _config_hash(config: dict[str, Any]) -> str:
    """Create a hashable key from config dict."""
    return json.dumps(config, sort_keys=True, default=str)


def get_evaluator(evaluator_config: EvaluatorConfig) -> PluginEvaluator[Any]:
    """Get or create a cached evaluator instance from configuration.

    Uses LRU caching to reuse evaluator instances with the same config.
    Cache key is: {plugin_name}:{config_hash}

    Args:
        evaluator_config: The evaluator configuration with plugin name and config

    Returns:
        PluginEvaluator instance (cached or new)

    Raises:
        ValueError: If plugin not found
    """
    # Build cache key
    cache_key = f"{evaluator_config.plugin}:{_config_hash(evaluator_config.config)}"

    # Check cache
    if cache_key in _EVALUATOR_CACHE:
        # Move to end (most recently used)
        _EVALUATOR_CACHE.move_to_end(cache_key)
        logger.debug(f"Cache hit for evaluator: {evaluator_config.plugin}")
        return _EVALUATOR_CACHE[cache_key]

    # Cache miss - create new instance
    plugin_cls = get_plugin(evaluator_config.plugin)

    if plugin_cls is None:
        raise ValueError(
            f"Plugin '{evaluator_config.plugin}' not found. "
            f"Available plugins: {', '.join(get_available_plugins())}"
        )

    logger.debug(f"Cache miss, creating evaluator: {evaluator_config.plugin}")
    instance = plugin_cls.from_dict(evaluator_config.config)

    # Evict oldest if cache is full
    while len(_EVALUATOR_CACHE) >= EVALUATOR_CACHE_SIZE:
        evicted_key, _ = _EVALUATOR_CACHE.popitem(last=False)
        logger.debug(f"Evicted evaluator from cache: {evicted_key}")

    # Cache the instance
    _EVALUATOR_CACHE[cache_key] = instance
    return instance


def invalidate_evaluator_cache(plugin_name: str) -> int:
    """Invalidate all cached instances for a plugin.

    Call this when a custom evaluator's code is updated.

    Args:
        plugin_name: Name of the plugin to invalidate

    Returns:
        Number of cache entries invalidated
    """
    keys_to_remove = [k for k in _EVALUATOR_CACHE if k.startswith(f"{plugin_name}:")]
    for key in keys_to_remove:
        del _EVALUATOR_CACHE[key]
        logger.debug(f"Invalidated evaluator cache: {key}")
    return len(keys_to_remove)


def clear_evaluator_cache() -> None:
    """Clear all cached evaluator instances. Useful for testing."""
    _EVALUATOR_CACHE.clear()


def get_evaluator_cache_stats() -> dict[str, int]:
    """Get cache statistics for monitoring."""
    return {
        "cache_size": len(_EVALUATOR_CACHE),
        "cache_limit": EVALUATOR_CACHE_SIZE,
    }


def get_available_plugins() -> list[str]:
    """Get list of available plugin names."""
    from agent_control_models import list_plugins

    return list(list_plugins().keys())
