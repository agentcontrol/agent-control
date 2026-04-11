"""BudgetStore abstract base class -- interface for budget storage backends.

Implementations must provide atomic record-and-check: a single call
that records usage and returns the current totals. This prevents
read-then-write race conditions under concurrent access.

Built-in: InMemoryBudgetStore (dict + threading.Lock).
External: Redis, PostgreSQL, etc. (separate packages).
"""

from __future__ import annotations

import inspect
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import BudgetLimitRule


@dataclass(frozen=True)
class BudgetSnapshot:
    """Immutable view of budget state at a point in time.

    Attributes:
        spent: Cumulative spend in cents (USD), rounded from float.
        spent_tokens: Cumulative tokens (input + output) in this scope+period.
        limit: Configured ceiling, interpreted by limit_unit.
        utilization: Selected usage ratio clamped to [0.0, 1.0].
        exceeded: True when the configured limit is breached.
        limit_unit: Unit used to interpret limit.
    """

    spent: int
    spent_tokens: int
    limit: int | None
    utilization: float
    exceeded: bool
    limit_unit: str = "usd_cents"


def round_spent(value: float) -> int:
    """Truncate accumulated float spend to integer cents for display.

    Uses floor truncation (not rounding) so that the displayed spent
    value never exceeds the actual float. This prevents a contradictory
    snapshot where spent >= limit but exceeded is False.
    """
    if not math.isfinite(value) or value < 0:
        return 0
    return int(value)


class BudgetStore(ABC):
    """Abstract base class for budget storage backends.

    The store owns bucket state and derives period keys internally from
    window_seconds + current time. Callers pass the rules to evaluate for
    each record operation along with usage data: scope dict, input_tokens,
    output_tokens, cost.

    Negative `cost` values are permitted and reduce accumulated spend (refund
    semantics). `round_spent()` floors the displayed snapshot spend to 0 for
    negative accumulators, but the internal float accumulator may go negative
    so that a subsequent positive charge cancels correctly. Validation of
    cost >= 0 is NOT performed at the store boundary; it is the caller's
    responsibility if strict positive accounting is required.

    Implementations should be safe to call from async contexts.
    InMemoryBudgetStore wraps a sync critical section under threading.Lock
    because the work is CPU-bound and brief; distributed backends
    (Redis/Postgres) should use native async I/O.

    Subclasses must override `record_and_check` with a coroutine function
    (`async def`). A sync override is rejected at class creation time rather
    than failing silently at the first `await` site in production.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Walk the MRO to find the nearest override of record_and_check.
        # Checking only cls.__dict__ misses mixin-inherited sync overrides
        # that satisfy ABC's abstractmethod check but silently break at the
        # first `await` call site.
        method = None
        for base in cls.__mro__:
            if base is BudgetStore:
                break
            if "record_and_check" in base.__dict__:
                raw = base.__dict__["record_and_check"]
                # Unwrap staticmethod/classmethod descriptors so that
                # inspect.iscoroutinefunction sees the underlying function.
                method = getattr(raw, "__func__", raw)
                break
        if method is not None and not inspect.iscoroutinefunction(method):
            raise TypeError(
                f"{cls.__name__}.record_and_check must be an async def "
                "(coroutine function); got a sync function. BudgetStore is "
                "an async ABC."
            )

    @abstractmethod
    async def record_and_check(
        self,
        rules: list[BudgetLimitRule],
        scope: dict[str, str],
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> list[BudgetSnapshot]:
        """Atomically record usage and return snapshots for all matching rules.

        Args:
            rules: Rules to evaluate against the shared bucket state.
            scope: Scope dimensions from the step (e.g. {"agent": "summarizer"}).
            input_tokens: Input tokens consumed by this call.
            output_tokens: Output tokens consumed by this call.
            cost: Cost in cents (USD), as a float for precision.

        Returns:
            List of BudgetSnapshot, one per matching rule.
        """
