"""Rule factory with instance caching."""

from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from agent_control_rules._discovery import list_rules

if TYPE_CHECKING:
    from agent_control_models import RuleSpec

    from agent_control_rules._base import Rule

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_CACHE_SIZE = 100
MIN_CACHE_SIZE = 1  # Minimum to avoid infinite loop in eviction


def _parse_cache_size() -> int:
    """Parse RULE_CACHE_SIZE from env with safe fallback."""
    raw = os.environ.get("RULE_CACHE_SIZE")
    if raw is None:
        return DEFAULT_CACHE_SIZE
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            f"Invalid RULE_CACHE_SIZE '{raw}', using default {DEFAULT_CACHE_SIZE}"
        )
        return DEFAULT_CACHE_SIZE


RULE_CACHE_SIZE = max(_parse_cache_size(), MIN_CACHE_SIZE)

# LRU cache for rule instances: cache_key -> Rule instance
_RULE_CACHE: OrderedDict[str, Rule[Any]] = OrderedDict()


def _config_hash(config: dict[str, Any]) -> str:
    """Create a hashable key from config dict."""
    return json.dumps(config, sort_keys=True, default=str)


def get_rule_instance(rule_spec: RuleSpec) -> Rule[Any]:
    """Get or create a cached rule instance from specification.

    Uses LRU caching to reuse rule instances with the same config.
    Cache key is: {rule_name}:{config_hash}

    WARNING: Rule instances are cached and reused across requests!
    Rule implementations MUST be stateless - do not store mutable
    request-scoped state on the rule instance. See Rule
    docstring for details on safe patterns.

    Args:
        rule_spec: The rule specification with name and config

    Returns:
        Rule instance (cached or new)

    Raises:
        ValueError: If rule not found
    """
    # Build cache key
    cache_key = f"{rule_spec.name}:{_config_hash(rule_spec.config)}"

    # Check cache
    if cache_key in _RULE_CACHE:
        # Move to end (most recently used)
        _RULE_CACHE.move_to_end(cache_key)
        logger.debug(f"Cache hit for rule: {rule_spec.name}")
        return _RULE_CACHE[cache_key]

    # Cache miss - create new instance
    rules = list_rules()
    rule_cls = rules.get(rule_spec.name)

    if rule_cls is None:
        raise ValueError(
            f"Rule '{rule_spec.name}' not found. "
            f"Available rules: {', '.join(rules.keys())}"
        )

    logger.debug(f"Cache miss, creating rule: {rule_spec.name}")
    instance = rule_cls.from_dict(rule_spec.config)

    # Evict oldest if cache is full
    while len(_RULE_CACHE) >= RULE_CACHE_SIZE:
        evicted_key, _ = _RULE_CACHE.popitem(last=False)
        logger.debug(f"Evicted rule from cache: {evicted_key}")

    # Cache the instance
    _RULE_CACHE[cache_key] = instance
    return instance


def clear_rule_cache() -> None:
    """Clear all cached rule instances. Useful for testing."""
    _RULE_CACHE.clear()
