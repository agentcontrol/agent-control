"""Agent Control Rules.

This package contains builtin rule implementations for agent-control.
Built-in rules (regex, list, json, sql) are registered automatically on import.

Available rules:
    Built-in (no namespace):
        - regex: Regular expression matching
        - list: List-based value matching
        - json: JSON validation
        - sql: SQL query validation

Naming convention:
    - Built-in: "regex", "list", "json", "sql"
    - External: "provider.name" (e.g., "galileo.luna")
    - Agent-scoped: "agent:name" (custom code deployed with agent)

External rules are installed via separate packages (e.g., agent-control-rule-galileo).
Custom rules are Rule classes deployed with the engine.
Their schemas are registered via initAgent for validation purposes.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-rules")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

# Core infrastructure - export from _base and _registry
from agent_control_rules._base import (
    Rule,
    RuleConfig,
    RuleMetadata,
)
from agent_control_rules._discovery import (
    discover_rules,
    ensure_rules_discovered,
    list_rules,
    reset_rule_discovery,
)
from agent_control_rules._factory import clear_rule_cache, get_rule_instance
from agent_control_rules._registry import (
    clear_rules,
    get_all_rules,
    get_rule,
    register_rule,
)

# Import built-in rules to auto-register them
from agent_control_rules.json import JSONRule, JSONRuleConfig
from agent_control_rules.list import ListRule, ListRuleConfig
from agent_control_rules.regex import RegexRule, RegexRuleConfig
from agent_control_rules.sql import SQLRule, SQLRuleConfig

__all__ = [
    # Core infrastructure
    "Rule",
    "RuleConfig",
    "RuleMetadata",
    "register_rule",
    "get_rule",
    "get_all_rules",
    "clear_rules",
    "discover_rules",
    "ensure_rules_discovered",
    "reset_rule_discovery",
    "list_rules",
    "get_rule_instance",
    "clear_rule_cache",
    # Built-in rules
    "RegexRule",
    "RegexRuleConfig",
    "ListRule",
    "ListRuleConfig",
    "JSONRule",
    "JSONRuleConfig",
    "SQLRule",
    "SQLRuleConfig",
]
