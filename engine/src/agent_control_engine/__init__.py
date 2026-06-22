"""Agent Control Engine - Rule execution logic and rule system."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-engine")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from agent_control_rules import (
    clear_rule_cache,
    discover_rules,
    ensure_rules_discovered,
    get_rule_instance,
    list_rules,
    reset_rule_discovery,
)

__all__ = [
    "clear_rule_cache",
    "discover_rules",
    "ensure_rules_discovered",
    "get_rule_instance",
    "list_rules",
    "reset_rule_discovery",
]
