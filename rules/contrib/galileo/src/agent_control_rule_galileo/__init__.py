"""Agent Control Rule - Galileo.

This package provides Galileo rules for agent-control.

Available rules:
    - galileo.luna: Galileo Luna direct scorer evaluation

Installation:
    pip install agent-control-rule-galileo

Or via the agent-control-rules convenience extra:
    pip install agent-control-rules[galileo]
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-rule-galileo")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from agent_control_rule_galileo.luna import (
    LUNA_AVAILABLE,
    GalileoLunaClient,
    LunaOperator,
    LunaRule,
    LunaRuleConfig,
    ScorerInvokeRequest,
    ScorerInvokeResponse,
)

__all__ = [
    "GalileoLunaClient",
    "ScorerInvokeRequest",
    "ScorerInvokeResponse",
    "LunaRule",
    "LunaRuleConfig",
    "LunaOperator",
    "LUNA_AVAILABLE",
]
