"""Rule system for agent_control.

This module provides a rule architecture for extending agent_control
with external evaluation systems like Galileo Luna, Guardrails AI, etc.

Rule Discovery:
    Call `discover_rules()` at startup to load rules. This loads:
    - Built-in rules (regex, list, json, sql) from agent_control_rules
    - Third-party rules via the 'agent_control.rules' entry point group

    Then use `list_rules()` to get available rules.

Galileo rules:
    When installed with galileo extras, the Galileo rule types are available:
    ```python
    from agent_control.rules import LunaRule, LunaRuleConfig  # if galileo installed
    ```
"""

from agent_control_engine import (
    discover_rules,
    ensure_rules_discovered,
    list_rules,
)
from agent_control_rules import register_rule

from .base import Rule, RuleMetadata

__all__ = [
    "Rule",
    "RuleMetadata",
    "discover_rules",
    "ensure_rules_discovered",
    "list_rules",
    "register_rule",
]

# Optionally export Luna types when available
try:
    from agent_control_rule_galileo.luna import (  # type: ignore[import-not-found]  # noqa: F401
        LUNA_AVAILABLE,
        GalileoLunaClient,
        LunaOperator,
        LunaRule,
        LunaRuleConfig,
        ScorerInvokeInputs,
        ScorerInvokeRequest,
        ScorerInvokeResponse,
    )

    __all__.extend(
        [
            "GalileoLunaClient",
            "ScorerInvokeInputs",
            "ScorerInvokeRequest",
            "ScorerInvokeResponse",
            "LunaRule",
            "LunaRuleConfig",
            "LunaOperator",
            "LUNA_AVAILABLE",
        ]
    )
except ImportError:
    pass
