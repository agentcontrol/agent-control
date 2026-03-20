"""SpendStore protocol and built-in InMemorySpendStore implementation.

The SpendStore abstraction decouples the spend-limit evaluator from any
particular persistence backend.  The default ``InMemorySpendStore`` requires no
external dependencies and is suitable for single-process deployments or testing.

For production multi-process or multi-replica deployments you should implement a
custom SpendStore backed by a durable store such as PostgreSQL or Redis.  See
README.md for an example.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SpendStore(Protocol):
    """Protocol that all spend store implementations must satisfy.

    Implementations are free to choose any persistence mechanism (in-memory,
    Redis, PostgreSQL, …).  Both methods must be thread-safe.
    """

    def record_spend(
        self,
        amount: float,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a completed (or pending) spend record.

        Args:
            amount: Positive monetary amount that was spent.
            currency: ISO-4217 or token symbol (e.g. ``"USDC"``).
            metadata: Optional key-value bag for agent_id, session_id, etc.
        """
        ...

    def get_spend(
        self,
        currency: str,
        since_timestamp: float,
        scope: dict[str, str] | None = None,
    ) -> float:
        """Return total spend for *currency* since *since_timestamp*.

        Args:
            currency: Currency symbol to query (case-sensitive).
            since_timestamp: Unix timestamp (seconds).  Only records whose
                ``recorded_at`` is >= this value are included.
            scope: Optional key-value pairs to filter by metadata fields.
                For example, ``{"channel": "slack"}`` returns only spend
                recorded with that channel in metadata.  When None, returns
                all spend regardless of metadata.

        Returns:
            Sum of all matching spend amounts.  Returns 0.0 when no records
            match.
        """
        ...


class _SpendRecord:
    """Internal record stored by :class:`InMemorySpendStore`."""

    __slots__ = ("amount", "currency", "recorded_at", "metadata")

    def __init__(
        self,
        amount: float,
        currency: str,
        recorded_at: float,
        metadata: dict[str, Any] | None,
    ) -> None:
        self.amount = amount
        self.currency = currency
        self.recorded_at = recorded_at
        self.metadata = metadata

    def matches_scope(self, scope: dict[str, str]) -> bool:
        """Check if this record's metadata matches all scope key-value pairs."""
        if not self.metadata:
            return False
        return all(
            self.metadata.get(k) == v
            for k, v in scope.items()
        )


class InMemorySpendStore:
    """Thread-safe in-memory implementation of :class:`SpendStore`.

    Records are kept in a ``deque`` ordered by insertion time.  A background
    sweep prunes records older than *max_age_seconds* to prevent unbounded
    memory growth.

    This implementation is **not** suitable for multi-process or distributed
    deployments because each process maintains an independent ledger.  Use it
    for single-process services, local development, and tests.

    Args:
        max_age_seconds: Records older than this many seconds are eligible for
            pruning.  Defaults to 7 days (604 800 s).
    """

    def __init__(self, max_age_seconds: int = 604_800) -> None:
        self._max_age_seconds = max_age_seconds
        self._records: deque[_SpendRecord] = deque()
        self._lock = Lock()

    # ------------------------------------------------------------------
    # SpendStore protocol implementation
    # ------------------------------------------------------------------

    def record_spend(
        self,
        amount: float,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a spend event at the current wall-clock time.

        Args:
            amount: Positive monetary amount.
            currency: Currency symbol (e.g. ``"USDC"``).
            metadata: Optional context bag (agent_id, session_id, channel, …).
        """
        if amount <= 0:
            raise ValueError(f"amount must be positive, got {amount!r}")

        now = time.time()
        record = _SpendRecord(
            amount=amount,
            currency=currency,
            recorded_at=now,
            metadata=metadata,
        )
        with self._lock:
            self._records.append(record)
            self._prune_locked(now)

    def get_spend(
        self,
        currency: str,
        since_timestamp: float,
        scope: dict[str, str] | None = None,
    ) -> float:
        """Sum all spend for *currency* since *since_timestamp*.

        Args:
            currency: Currency symbol (case-sensitive).
            since_timestamp: Unix epoch seconds (inclusive lower bound).
            scope: Optional metadata filter.  When provided, only records
                whose metadata contains all specified key-value pairs are
                included.  When None, all records for the currency are summed.

        Returns:
            Total spend as a float.
        """
        with self._lock:
            total = 0.0
            for r in self._records:
                if r.currency != currency or r.recorded_at < since_timestamp:
                    continue
                if scope is not None and not r.matches_scope(scope):
                    continue
                total += r.amount
            return total

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune_locked(self, now: float) -> None:
        """Remove records older than *max_age_seconds* (called with lock held)."""
        cutoff = now - self._max_age_seconds
        while self._records and self._records[0].recorded_at < cutoff:
            self._records.popleft()

    def record_count(self) -> int:
        """Return the current number of stored records (useful for tests)."""
        with self._lock:
            return len(self._records)
