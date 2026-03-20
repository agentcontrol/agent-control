"""Financial governance evaluators for agent-control.

Provides two evaluators for enforcing financial policy on AI agent transactions:

- ``financial_governance.spend_limit``: Tracks cumulative spend against rolling
  period budgets and per-transaction caps.
- ``financial_governance.transaction_policy``: Static policy checks — allowlists,
  blocklists, amount bounds, and permitted currencies.

Both evaluators are registered automatically when this package is installed and
the ``agent_control.evaluators`` entry point group is discovered.

Example usage in an agent-control control config::

    {
      "condition": {
        "selector": {"path": "*"},
        "evaluator": {
          "name": "financial_governance.spend_limit",
          "config": {
            "max_per_transaction": 100.0,
            "max_per_period": 1000.0,
            "period_seconds": 86400,
            "currency": "USDC"
          }
        }
      },
      "action": {"decision": "deny"}
    }
"""

from agent_control_evaluator_financial_governance.spend_limit import (
    SpendLimitConfig,
    SpendLimitEvaluator,
)
from agent_control_evaluator_financial_governance.transaction_policy import (
    TransactionPolicyConfig,
    TransactionPolicyEvaluator,
)

__all__ = [
    "SpendLimitEvaluator",
    "SpendLimitConfig",
    "TransactionPolicyEvaluator",
    "TransactionPolicyConfig",
]
