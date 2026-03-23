"""Financial governance evaluators for agent-control.

Provides two evaluators for enforcing financial policy on AI agent transactions:

- ``financial_governance.spend_limit``: Tracks cumulative spend against rolling
  period budgets and per-transaction caps.  Uses the :class:`BudgetLimit` /
  :class:`BudgetWindow` model for expressive, scoped budget definitions.
- ``financial_governance.transaction_policy``: Static policy checks — allowlists,
  blocklists, amount bounds, and permitted currencies.

Both evaluators are registered automatically when this package is installed and
the ``agent_control.evaluators`` entry point group is discovered.

Example usage in an agent-control control config::

    {
      "condition": {
        "selector": {"path": "input"},
        "evaluator": {
          "name": "financial_governance.spend_limit",
          "config": {
            "limits": [
              {
                "amount": "100.00",
                "currency": "USDC"
              },
              {
                "amount": "1000.00",
                "currency": "USDC",
                "scope_by": ["channel"],
                "window": {"kind": "rolling", "seconds": 86400}
              }
            ]
          }
        }
      },
      "action": {"decision": "deny"}
    }
"""

from agent_control_evaluator_financial_governance.spend_limit import (
    BudgetLimit,
    BudgetWindow,
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
    "BudgetLimit",
    "BudgetWindow",
    "TransactionPolicyEvaluator",
    "TransactionPolicyConfig",
]
