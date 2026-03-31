"""In-memory budget store implementation.

Not suitable for multi-process deployments. For distributed setups,
use a Redis or Postgres-backed store (separate package).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import BudgetLimitRule
from .store import BudgetSnapshot


def _sanitize_scope_value(val: str) -> str:
    """Percent-encode pipe and equals in scope values to prevent key injection."""
    return val.replace("%", "%25").replace("|", "%7C").replace("=", "%3D")


def _build_scope_key(
    rule_scope: dict[str, str],
    group_by: str | None,
    step_scope: dict[str, str],
) -> str:
    """Build a composite scope key from rule dimensions and group_by field."""
    parts: list[str] = []
    for k, v in sorted(rule_scope.items()):
        parts.append(f"{k}={_sanitize_scope_value(v)}")
    if group_by and group_by in step_scope:
        parts.append(f"{group_by}={_sanitize_scope_value(step_scope[group_by])}")
    return "|".join(parts) if parts else "__global__"


def _derive_period_key(window_seconds: int | None, now: float) -> str:
    """Derive a period key from window_seconds and a timestamp.

    Periods are aligned to UTC epoch boundaries. For example,
    window_seconds=86400 produces keys like "P86400:19800" where
    19800 is the number of complete windows since epoch.
    """
    if window_seconds is None:
        return ""
    period_index = int(now) // window_seconds
    return f"P{window_seconds}:{period_index}"


def _scope_matches(rule: BudgetLimitRule, scope: dict[str, str]) -> bool:
    """Check if rule's scope dimensions match step scope."""
    for key, expected in rule.scope.items():
        if scope.get(key) != expected:
            return False
    if rule.group_by and rule.group_by not in scope:
        return False
    return True


def _compute_utilization(
    spent: int,
    spent_tokens: int,
    limit: int | None,
    limit_tokens: int | None,
) -> float:
    """Return max(spend_ratio, token_ratio) clamped to [0.0, 1.0]."""
    ratios: list[float] = []
    if limit is not None and limit > 0:
        ratios.append(min(spent / limit, 1.0))
    if limit_tokens is not None and limit_tokens > 0:
        ratios.append(min(spent_tokens / limit_tokens, 1.0))
    return max(ratios) if ratios else 0.0


@dataclass
class _Bucket:
    """Internal mutable accumulator for a single (scope, period) pair."""

    spent: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class InMemoryBudgetStore:
    """Thread-safe in-memory budget store.

    Initialized with a list of BudgetLimitRule. Derives period keys
    internally from window_seconds + injected clock.

    NOTE: Currency conversion is not handled here. The cost integer
    passed to record_and_check is assumed to be in the same unit as
    the rule's currency. Cross-currency conversion (e.g. USD->EUR)
    is the caller's responsibility and will be addressed when cost
    calculation moves into the evaluator (pending design review).
    """

    _DEFAULT_MAX_BUCKETS = 100_000

    def __init__(
        self,
        rules: list[BudgetLimitRule],
        *,
        clock: Callable[[], float] = time.time,
        max_buckets: int = _DEFAULT_MAX_BUCKETS,
    ) -> None:
        self._rules = rules
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str, str], _Bucket] = {}
        self._max_buckets = max_buckets

    def record_and_check(
        self,
        scope: dict[str, str],
        input_tokens: int,
        output_tokens: int,
        cost: int,
    ) -> list[BudgetSnapshot]:
        """Atomically record usage and return snapshots for all matching rules."""
        now = self._clock()
        snapshots: list[BudgetSnapshot] = []
        recorded_pairs: set[tuple[str, str, str]] = set()

        with self._lock:
            for rule in self._rules:
                if not _scope_matches(rule, scope):
                    continue

                scope_key = _build_scope_key(rule.scope, rule.group_by, scope)
                period_key = _derive_period_key(rule.window_seconds, now)
                cur = rule.currency
                currency_key = cur.value if hasattr(cur, "value") else str(cur)
                pair = (scope_key, period_key, currency_key)

                if pair not in recorded_pairs:
                    bucket = self._get_or_create_bucket(pair)
                    if bucket is None:
                        # Max buckets reached -- fail closed
                        snapshots.append(
                            BudgetSnapshot(
                                spent=0,
                                spent_tokens=0,
                                limit=rule.limit,
                                limit_tokens=rule.limit_tokens,
                                utilization=1.0,
                                exceeded=True,
                            )
                        )
                        continue
                    bucket.spent += cost
                    bucket.input_tokens += input_tokens
                    bucket.output_tokens += output_tokens
                    recorded_pairs.add(pair)
                else:
                    bucket = self._buckets.get(pair)
                    if bucket is None:
                        continue

                total_tokens = bucket.total_tokens
                utilization = _compute_utilization(
                    bucket.spent, total_tokens, rule.limit, rule.limit_tokens
                )
                exceeded = False
                if rule.limit is not None and bucket.spent >= rule.limit:
                    exceeded = True
                if rule.limit_tokens is not None and total_tokens >= rule.limit_tokens:
                    exceeded = True

                snapshots.append(
                    BudgetSnapshot(
                        spent=bucket.spent,
                        spent_tokens=total_tokens,
                        limit=rule.limit,
                        limit_tokens=rule.limit_tokens,
                        utilization=utilization,
                        exceeded=exceeded,
                    )
                )

        return snapshots

    def get_snapshot(
        self,
        scope_key: str,
        period_key: str,
        limit: int | None = None,
        limit_tokens: int | None = None,
        currency: str = "usd",
    ) -> BudgetSnapshot:
        """Read current budget state without recording usage."""
        key = (scope_key, period_key, currency)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return BudgetSnapshot(
                    spent=0,
                    spent_tokens=0,
                    limit=limit,
                    limit_tokens=limit_tokens,
                    utilization=0.0,
                    exceeded=False,
                )
            total_tokens = bucket.total_tokens
            utilization = _compute_utilization(bucket.spent, total_tokens, limit, limit_tokens)
            exceeded = False
            if limit is not None and bucket.spent >= limit:
                exceeded = True
            if limit_tokens is not None and total_tokens >= limit_tokens:
                exceeded = True
            return BudgetSnapshot(
                spent=bucket.spent,
                spent_tokens=total_tokens,
                limit=limit,
                limit_tokens=limit_tokens,
                utilization=utilization,
                exceeded=exceeded,
            )

    def reset(self, scope_key: str | None = None, period_key: str | None = None) -> None:
        """Clear accumulated usage."""
        with self._lock:
            if scope_key is None and period_key is None:
                self._buckets.clear()
                return
            keys_to_remove = [
                k
                for k in self._buckets
                if (scope_key is None or k[0] == scope_key)
                and (period_key is None or k[1] == period_key)
            ]
            for k in keys_to_remove:
                del self._buckets[k]

    def _get_or_create_bucket(self, key: tuple[str, str, str]) -> _Bucket | None:
        """Get or create a bucket. Returns None if max_buckets reached."""
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket
        if len(self._buckets) >= self._max_buckets:
            return None
        bucket = _Bucket()
        self._buckets[key] = bucket
        return bucket
