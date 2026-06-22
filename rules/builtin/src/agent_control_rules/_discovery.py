"""Rule discovery via entry points."""

from __future__ import annotations

import logging
import threading
from importlib import import_module
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from agent_control_rules._registry import (
    get_all_rules,
    get_rule,
    register_rule,
)

if TYPE_CHECKING:
    from agent_control_rules._base import Rule

logger = logging.getLogger(__name__)

_DISCOVERY_COMPLETE = False
_DISCOVERY_LOCK = threading.Lock()

_BUILTIN_RULES = (
    ("regex", "agent_control_rules.regex", "RegexRule"),
    ("list", "agent_control_rules.list", "ListRule"),
    ("json", "agent_control_rules.json", "JSONRule"),
    ("sql", "agent_control_rules.sql", "SQLRule"),
)


def _register_rule_class(rule_class: type[Rule[Any]]) -> bool:
    name = rule_class.metadata.name

    if get_rule(name) is not None:
        return False

    if not rule_class.is_available():
        logger.debug(f"Rule '{name}' not available, skipping")
        return False

    register_rule(rule_class)
    logger.debug(f"Registered rule: {name}")
    return True


def _discover_builtin_rules_from_source() -> int:
    """Register builtin rules when package entry points are unavailable.

    This fallback is mainly for direct source-tree execution where the package
    has not been installed and importlib.metadata has no entry-point metadata.
    """
    discovered = 0

    for entry_point_name, module_name, class_name in _BUILTIN_RULES:
        try:
            module = import_module(module_name)
            rule_class = getattr(module, class_name)
            if _register_rule_class(rule_class):
                discovered += 1
        except Exception as e:
            logger.warning(f"Failed to load rule '{entry_point_name}': {e}")

    return discovered


def discover_rules() -> int:
    """Discover and register rules via entry points.

    All rules (built-in and third-party) are discovered via the
    'agent_control.rules' entry point group. Rules are only registered
    if their `is_available()` method returns True.

    Safe to call multiple times - only runs discovery once.
    Thread-safe via lock.

    Returns:
        Number of rules discovered
    """
    global _DISCOVERY_COMPLETE

    # Fast path without lock
    if _DISCOVERY_COMPLETE:
        return 0

    with _DISCOVERY_LOCK:
        # Double-check after acquiring lock
        if _DISCOVERY_COMPLETE:
            return 0

        discovered = 0

        # Discover ALL rules (built-in and third-party) via entry points.
        # Only register rules where is_available() returns True.
        try:
            eps = list(entry_points(group="agent_control.rules"))
            for ep in eps:
                try:
                    rule_class = ep.load()
                    if _register_rule_class(rule_class):
                        discovered += 1
                except Exception as e:
                    logger.warning(f"Failed to load rule '{ep.name}': {e}")

            if not eps:
                discovered += _discover_builtin_rules_from_source()
        except Exception as e:
            logger.debug(f"Entry point discovery not available: {e}")

        _DISCOVERY_COMPLETE = True
        logger.debug(f"Rule discovery complete: {discovered} new rules")
        return discovered


def ensure_rules_discovered() -> None:
    """Ensure rule discovery has run. Call this before using rules."""
    if not _DISCOVERY_COMPLETE:
        discover_rules()


def reset_rule_discovery() -> None:
    """Reset discovery state. Useful for testing."""
    global _DISCOVERY_COMPLETE
    with _DISCOVERY_LOCK:
        _DISCOVERY_COMPLETE = False


# =============================================================================
# Public rule API
# =============================================================================


def list_rules() -> dict[str, type[Rule[Any]]]:
    """List all registered rules.

    This function ensures rule discovery has run before returning results.

    Returns:
        Dictionary mapping rule names to rule classes
    """
    ensure_rules_discovered()
    return get_all_rules()
