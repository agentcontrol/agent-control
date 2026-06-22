"""Base classes for agent_control rules.

Re-exports from agent_control_rules for convenience.
"""

# Re-export from the rules package (where they're now defined)
from agent_control_rules import Rule, RuleMetadata

__all__ = ["Rule", "RuleMetadata"]
