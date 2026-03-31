"""BudgetStore protocol -- interface for budget storage backends.

Implementations must provide atomic record-and-check: a single call
that records usage and returns the current totals. This prevents
read-then-write race conditions under concurrent access.

Built-in: InMemoryBudgetStore (dict + threading.Lock).
External: Redis, PostgreSQL, etc. (separate packages).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class BudgetSnapshot:
    """Immutable view of budget state at a point in time.

    Attributes:
        spent: Cumulative spend in minor units (e.g. cents for USD).
        spent_tokens: Cumulative tokens (input + output) in this scope+period.
        limit: Configured spend ceiling in minor units, or None if uncapped.
        limit_tokens: Configured token ceiling, or None if uncapped.
        utilization: max(spend_ratio, token_ratio) clamped to [0.0, 1.0].
            0.0 when no limits are set.
        exceeded: True when any limit is breached.
    """

    spent: int
    spent_tokens: int
    limit: int | None
    limit_tokens: int | None
    utilization: float
    exceeded: bool


@runtime_checkable
class BudgetStore(Protocol):
    """Protocol for budget storage backends.

    The store is initialized with a list of BudgetLimitRule and derives
    period keys internally from window_seconds + current time.

    Callers pass only usage data: scope dict, input_tokens, output_tokens, cost.
    """

    def record_and_check(
        self,
        scope: dict[str, str],
        input_tokens: int,
        output_tokens: int,
        cost: int,
    ) -> list[BudgetSnapshot]:
        """Atomically record usage and return snapshots for all matching rules.

        Args:
            scope: Scope dimensions from the step (e.g. {"agent": "summarizer"}).
            input_tokens: Input tokens consumed by this call.
            output_tokens: Output tokens consumed by this call.
            cost: Cost in minor units (e.g. cents for USD).

        Returns:
            List of BudgetSnapshot, one per matching rule.
        """
        ...
