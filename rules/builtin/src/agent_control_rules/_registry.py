"""Rule registry for registration and lookup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_control_rules._base import Rule

logger = logging.getLogger(__name__)

# =============================================================================
# Rule Registry
# =============================================================================

_RULE_REGISTRY: dict[str, type[Rule[Any]]] = {}


def register_rule(
    rule_class: type[Rule[Any]],
) -> type[Rule[Any]]:
    """Register a rule class by its metadata name.

    Can be used as a decorator or called directly. Respects the rule's
    is_available() method - rules with unavailable dependencies are
    silently skipped.

    Args:
        rule_class: Rule class to register

    Returns:
        The same rule class (for decorator usage)

    Raises:
        ValueError: If rule name already registered with different class

    Example:
        ```python
        @register_rule
        class MyRule(Rule[MyConfig]):
            metadata = RuleMetadata(name="my-rule", ...)
            ...
        ```
    """
    name = rule_class.metadata.name

    # Check if rule dependencies are satisfied
    if not rule_class.is_available():
        logger.debug(f"Rule '{name}' not available (is_available=False), skipping")
        return rule_class

    if name in _RULE_REGISTRY:
        # Allow re-registration of same class (e.g., during hot reload)
        if _RULE_REGISTRY[name] is rule_class:
            return rule_class
        raise ValueError(f"Rule '{name}' is already registered")

    _RULE_REGISTRY[name] = rule_class
    logger.debug(f"Registered rule: {name} v{rule_class.metadata.version}")
    return rule_class


def get_rule(name: str) -> type[Rule[Any]] | None:
    """Get a registered rule by name.

    Args:
        name: Rule name to look up

    Returns:
        Rule class if found, None otherwise
    """
    return _RULE_REGISTRY.get(name)


def get_all_rules() -> dict[str, type[Rule[Any]]]:
    """Get all registered rules.

    Returns:
        Dictionary mapping rule names to rule classes
    """
    return dict(_RULE_REGISTRY)


def clear_rules() -> None:
    """Clear all registered rules. Useful for testing."""
    _RULE_REGISTRY.clear()
