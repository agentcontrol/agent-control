"""Agent Control DefenseClaw external evaluators."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-evaluator-defenseclaw")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from .common import Severity
from .opa_policy import DefenseClawOpaPolicyConfig, DefenseClawOpaPolicyEvaluator, OpaPolicy
from .rule_pack import (
    DefenseClawRulePackConfig,
    DefenseClawRulePackEvaluator,
    RuleConfig,
    RulePack,
)

__all__ = [
    "DefenseClawOpaPolicyConfig",
    "DefenseClawOpaPolicyEvaluator",
    "DefenseClawRulePackConfig",
    "DefenseClawRulePackEvaluator",
    "OpaPolicy",
    "RuleConfig",
    "RulePack",
    "Severity",
]
