"""In-memory budget store implementation.

Not suitable for multi-process deployments. For distributed setups,
use a Redis or Postgres-backed store (separate package).
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import BudgetLimitRule
from .store import BudgetSnapshot, BudgetStore, round_spent


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


def _parse_period_key(key: str) -> tuple[int, int] | None:
    """Parse 'P{window}:{index}' into (window_seconds, bucket_index).

    Returns None for empty/cumulative keys.
    """
    if not key or not key.startswith("P"):
        return None
    try:
        window_part, index_part = key[1:].split(":", 1)
        return int(window_part), int(index_part)
    except (ValueError, IndexError):
        return None


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
    spent: float,
    spent_tokens: int,
    limit: int | None,
    limit_unit: str,
) -> float:
    """Return the selected usage ratio clamped to [0.0, 1.0].

    The low-side clamp is load-bearing: under refund semantics the internal
    `spent` accumulator may go negative, which would otherwise produce a
    negative ratio and violate the BudgetSnapshot.utilization contract.
    """
    if limit_unit == "tokens":
        ratio = spent_tokens / limit if limit else 0.0
    else:
        ratio = spent / limit if limit else 0.0
    return max(0.0, min(ratio, 1.0))


@dataclass
class _Bucket:
    """Internal mutable accumulator for a single (scope, period) pair."""

    spent: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class InMemoryBudgetStore(BudgetStore):
    """Thread-safe in-memory budget store.

    Owns bucket state and derives period keys internally from
    window_seconds + injected clock. Callers provide the rules to evaluate
    on each record operation.

    Cost is accumulated as float for precision. Integer rounding
    happens only at snapshot time for display/reporting.

    TTL prune: on new period rollover per window, buckets older than
    `current - 1` for that window are dropped. This keeps memory bounded
    for long-running deployments with windowed rules.

    `max_buckets` remains as a backstop for high-cardinality group_by
    explosions that TTL cannot protect against.
    """

    _DEFAULT_MAX_BUCKETS = 100_000

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        max_buckets: int = _DEFAULT_MAX_BUCKETS,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._max_buckets = max_buckets
        self._last_pruned_period: dict[int, int] = {}

    async def record_and_check(
        self,
        rules: list[BudgetLimitRule],
        scope: dict[str, str],
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> list[BudgetSnapshot]:
        """Atomically record usage and return snapshots for all matching rules."""
        return self._record_and_check_sync(rules, scope, input_tokens, output_tokens, cost)

    def _record_and_check_sync(
        self,
        rules: list[BudgetLimitRule],
        scope: dict[str, str],
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> list[BudgetSnapshot]:
        """Sync implementation of record_and_check.

        NaN/Inf cost is coerced to 0.0 defensively. Once NaN enters a
        bucket's float accumulator, all subsequent additions produce NaN
        and `nan >= limit` is always False (IEEE 754), permanently
        disabling budget enforcement for that bucket.
        """
        if not math.isfinite(cost):
            cost = 0.0
        # Token counts have no refund semantics; clamp to non-negative
        # to prevent negative injection from resetting the accumulator.
        input_tokens = max(0, input_tokens)
        output_tokens = max(0, output_tokens)
        now = self._clock()
        if not math.isfinite(now):
            now = 0.0
        snapshots: list[BudgetSnapshot] = []
        recorded_pairs: set[tuple[str, str]] = set()

        with self._lock:
            for rule in rules:
                if not _scope_matches(rule, scope):
                    continue

                scope_key = _build_scope_key(rule.scope, rule.group_by, scope)
                period_key = _derive_period_key(rule.window_seconds, now)
                pair = (scope_key, period_key)

                if pair not in recorded_pairs:
                    bucket = self._get_or_create_bucket(pair)
                    if bucket is None:
                        # Max buckets reached -- fail closed
                        snapshots.append(
                            BudgetSnapshot(
                                spent=0,
                                spent_tokens=0,
                                limit=rule.limit,
                                utilization=1.0,
                                exceeded=True,
                                limit_unit=rule.limit_unit,
                            )
                        )
                        continue
                    bucket.spent += cost
                    bucket.input_tokens += input_tokens
                    bucket.output_tokens += output_tokens
                    recorded_pairs.add(pair)
                else:
                    bucket = self._buckets.get(pair)
                    # Defensive: this branch is unreachable under current
                    # invariants (recorded_pairs only contains pairs whose
                    # bucket was successfully created, and self._lock prevents
                    # concurrent deletion). If a future refactor violates
                    # this, the assertion surfaces it.
                    assert bucket is not None, (
                        f"bucket for {pair!r} was in recorded_pairs but missing from _buckets"
                    )

                total_tokens = bucket.total_tokens
                utilization = _compute_utilization(
                    bucket.spent, total_tokens, rule.limit, rule.limit_unit
                )
                if rule.limit_unit == "tokens":
                    exceeded = total_tokens >= rule.limit
                else:
                    exceeded = bucket.spent >= rule.limit

                snapshots.append(
                    BudgetSnapshot(
                        spent=round_spent(bucket.spent),
                        spent_tokens=total_tokens,
                        limit=rule.limit,
                        utilization=utilization,
                        exceeded=exceeded,
                        limit_unit=rule.limit_unit,
                    )
                )

        return snapshots

    def get_snapshot(
        self,
        scope_key: str,
        period_key: str,
        limit: int | None = None,
        limit_unit: str = "usd_cents",
    ) -> BudgetSnapshot:
        """Read current budget state without recording usage."""
        key = (scope_key, period_key)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return BudgetSnapshot(
                    spent=0,
                    spent_tokens=0,
                    limit=limit,
                    utilization=0.0,
                    exceeded=False,
                    limit_unit=limit_unit,
                )
            total_tokens = bucket.total_tokens
            utilization = _compute_utilization(bucket.spent, total_tokens, limit, limit_unit)
            if limit_unit == "tokens":
                exceeded = bool(limit is not None and total_tokens >= limit)
            else:
                exceeded = bool(limit is not None and bucket.spent >= limit)
            return BudgetSnapshot(
                spent=round_spent(bucket.spent),
                spent_tokens=total_tokens,
                limit=limit,
                utilization=utilization,
                exceeded=exceeded,
                limit_unit=limit_unit,
            )

    def reset(self, scope_key: str | None = None, period_key: str | None = None) -> None:
        """Clear accumulated usage."""
        with self._lock:
            if scope_key is None and period_key is None:
                self._buckets.clear()
                self._last_pruned_period.clear()
                return
            keys_to_remove = [
                k
                for k in self._buckets
                if (scope_key is None or k[0] == scope_key)
                and (period_key is None or k[1] == period_key)
            ]
            for k in keys_to_remove:
                del self._buckets[k]

    def _get_or_create_bucket(self, key: tuple[str, str]) -> _Bucket | None:
        """Get or create a bucket. Returns None if max_buckets reached.

        On period rollover (new windowed bucket with a forward period index),
        stale buckets for the same window (bucket_index < current - 1) are
        pruned BEFORE the max_buckets capacity check, so that a rollover at
        capacity can free space rather than fail closed. Cross-scope pruning
        is intentional: all stale same-window buckets are dropped regardless
        of scope key, since the period has expired globally.

        The watermark `_last_pruned_period[window]` only advances forward;
        a backwards clock does not trigger spurious prune work.

        Caller must hold self._lock.
        """
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket

        # TTL prune runs BEFORE the max_buckets check so that rollover at
        # capacity can reclaim space rather than fail closed permanently.
        parsed = _parse_period_key(key[1])
        if parsed is not None:
            window, index = parsed
            last_pruned = self._last_pruned_period.get(window)
            # Only advance on forward progress. Backwards clock is a no-op;
            # the previously established watermark still protects us.
            if last_pruned is None or index > last_pruned:
                stale_keys = [
                    k
                    for k in self._buckets
                    if (kp := _parse_period_key(k[1])) is not None
                    and kp[0] == window
                    and kp[1] < index - 1
                ]
                for k in stale_keys:
                    del self._buckets[k]
                self._last_pruned_period[window] = index

        if len(self._buckets) >= self._max_buckets:
            return None
        bucket = _Bucket()
        self._buckets[key] = bucket
        return bucket
