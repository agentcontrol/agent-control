"""Unified evaluator factory using evaluator registry with caching."""

import json
import logging
import os
from collections import OrderedDict
from typing import Any

from agent_control_models import Evaluator, EvaluatorConfig

from .discovery import list_evaluators

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_CACHE_SIZE = 100
MIN_CACHE_SIZE = 1  # Minimum to avoid infinite loop in eviction


def _parse_cache_size() -> int:
    """Parse EVALUATOR_CACHE_SIZE from env with safe fallback."""
    raw = os.environ.get("EVALUATOR_CACHE_SIZE")
    if raw is None:
        return DEFAULT_CACHE_SIZE
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            f"Invalid EVALUATOR_CACHE_SIZE '{raw}', using default {DEFAULT_CACHE_SIZE}"
        )
        return DEFAULT_CACHE_SIZE


EVALUATOR_CACHE_SIZE = max(_parse_cache_size(), MIN_CACHE_SIZE)

# LRU cache for evaluator instances: cache_key -> Evaluator instance
_EVALUATOR_CACHE: OrderedDict[str, Evaluator[Any]] = OrderedDict()


def _config_hash(config: dict[str, Any]) -> str:
    """Create a hashable key from config dict."""
    return json.dumps(config, sort_keys=True, default=str)


def get_evaluator_instance(evaluator_config: EvaluatorConfig) -> Evaluator[Any]:
    """Get or create a cached evaluator instance from configuration.

    Uses LRU caching to reuse evaluator instances with the same config.
    Cache key is: {evaluator_name}:{config_hash}

    WARNING: Evaluator instances are cached and reused across requests!
    Evaluator implementations MUST be stateless - do not store mutable
    request-scoped state on the evaluator instance. See Evaluator
    docstring for details on safe patterns.

    Args:
        evaluator_config: The evaluator configuration with evaluator name and config

    Returns:
        Evaluator instance (cached or new)

    Raises:
        ValueError: If evaluator not found
    """
    # Build cache key
    cache_key = f"{evaluator_config.name}:{_config_hash(evaluator_config.config)}"

    # Check cache
    if cache_key in _EVALUATOR_CACHE:
        # Move to end (most recently used)
        _EVALUATOR_CACHE.move_to_end(cache_key)
        logger.debug(f"Cache hit for evaluator: {evaluator_config.name}")
        return _EVALUATOR_CACHE[cache_key]

    # Cache miss - create new instance
    evaluators = list_evaluators()
    evaluator_cls = evaluators.get(evaluator_config.name)

    if evaluator_cls is None:
        raise ValueError(
            f"Evaluator '{evaluator_config.name}' not found. "
            f"Available evaluators: {', '.join(evaluators.keys())}"
        )

    logger.debug(f"Cache miss, creating evaluator: {evaluator_config.name}")
    instance = evaluator_cls.from_dict(evaluator_config.config)

    # Evict oldest if cache is full
    while len(_EVALUATOR_CACHE) >= EVALUATOR_CACHE_SIZE:
        evicted_key, _ = _EVALUATOR_CACHE.popitem(last=False)
        logger.debug(f"Evicted evaluator from cache: {evicted_key}")

    # Cache the instance
    _EVALUATOR_CACHE[cache_key] = instance
    return instance


def clear_evaluator_cache() -> None:
    """Clear all cached evaluator instances. Useful for testing."""
    _EVALUATOR_CACHE.clear()


