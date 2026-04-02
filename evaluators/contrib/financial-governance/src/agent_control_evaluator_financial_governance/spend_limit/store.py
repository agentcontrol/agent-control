"""SpendStore protocol and built-in InMemorySpendStore implementation.

The SpendStore abstraction decouples the spend-limit evaluator from any
particular persistence backend.  The default ``InMemorySpendStore`` requires no
external dependencies and is suitable for single-process deployments or testing.

For production multi-process or multi-replica deployments you should implement a
custom SpendStore backed by a durable store such as PostgreSQL or Redis.  See
README.md for an example.

Atomicity note
--------------
The ``check_and_record()`` method is the recommended path for enforcing hard
spend caps.  It atomically queries the current spend *and* records a new entry
(or rejects it) in a single operation, eliminating the TOCTOU race that exists
when callers do ``get_spend()`` followed by ``record_spend()`` separately.

The ``InMemorySpendStore`` implements atomicity with a threading ``Lock``.
This is safe within a single process but does NOT prevent overshoot across
multiple processes or replicas.  Production deployments that require strict
enforcement should use a backend with database-level atomics:

- **PostgreSQL**: ``SELECT SUM(...) FOR UPDATE`` + conditional ``INSERT``
  inside a single transaction.
- **Redis**: Lua script or ``MULTI``/``EXEC`` pipeline with a
  compare-and-swap pattern.

Document this single-process limitation prominently in any custom store
implementation so operators are not surprised by concurrent overshoot in
distributed deployments.
"""

from __future__ import annotations

import time
from collections import deque
from decimal import Decimal
from threading import Lock
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SpendStore(Protocol):
    """Protocol that all spend store implementations must satisfy.

    Implementations are free to choose any persistence mechanism.
    All methods must be thread-safe.

    Atomic enforcement
    ------------------
    Prefer ``check_and_record()`` over the separate ``get_spend()`` +
    ``record_spend()`` pattern.  The split pattern has a TOCTOU race condition:
    two concurrent requests can both read the same current spend, both decide
    they are within budget, and both record — overshooting the cap.

    ``check_and_record()`` performs the read-decide-write as a single atomic
    step.  For the ``InMemorySpendStore`` this is protected by a
    ``threading.Lock`` (single-process only).  Production stores should use
    DB-level atomics (see module docstring).
    """

    def record_spend(
        self,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a completed spend record.

        Args:
            amount: Positive monetary amount (Decimal — never float for money).
            currency: ISO-4217 or token symbol (e.g. ``"USDC"``).
            metadata: Optional key-value bag for agent_id, session_id, etc.
        """
        ...

    def get_spend(
        self,
        currency: str,
        start: float,
        end: float | None = None,
        scope: dict[str, str] | None = None,
    ) -> Decimal:
        """Return total spend for *currency* within the given time range.

        Args:
            currency: Currency symbol to query (case-sensitive).
            start: Unix timestamp (seconds, inclusive lower bound).
            end: Unix timestamp (seconds, inclusive upper bound).  ``None``
                means "up to now" — no upper bound is applied.
            scope: Optional key-value pairs to filter by metadata fields.
                For example, ``{"channel": "slack"}`` returns only spend
                recorded with that channel in metadata.  When None, returns
                all spend regardless of metadata.

                **Scope semantics (composite key):**
                All present keys together form a single composite scope key.
                A record with ``{"channel": "A", "agent_id": "bot-1"}`` will
                only match a scope of ``{"channel": "A", "agent_id": "bot-1"}``
                — NOT a query for ``{"channel": "A"}`` alone.

        Returns:
            Sum of all matching spend amounts as a Decimal.
        """
        ...

    def check_and_record(
        self,
        amount: Decimal,
        currency: str,
        limit: Decimal,
        start: float,
        end: float | None = None,
        scope: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, Decimal]:
        """Atomically check whether recording *amount* stays within *limit*
        and, if so, record it.

        Eliminates the TOCTOU race of separate ``get_spend()`` + ``record_spend()``.

        **Single-process atomicity only** for ``InMemorySpendStore``.
        Production stores must use DB-level atomics (see module docstring).

        Args:
            amount: Positive monetary amount of the proposed transaction.
            currency: Currency symbol (e.g. ``"USDC"``).
            limit: Maximum allowed total spend *including* this transaction.
                Rejected if ``current_spend + amount > limit``.
            start: Unix timestamp lower bound for the current-period query.
            end: Unix timestamp upper bound (``None`` = "up to now").
            scope: Optional metadata filter (same semantics as ``get_spend``).
            metadata: Metadata to attach to the new record if accepted.

        Returns:
            ``(accepted, current_spend)`` where:

            - ``accepted`` is ``True`` when within budget and recorded.
            - ``current_spend`` is total period spend *before* this transaction.
        """
        ...


class _SpendRecord:
    """Internal record stored by :class:`InMemorySpendStore`."""

    __slots__ = ("amount", "currency", "recorded_at", "metadata")

    def __init__(
        self,
        amount: Decimal,
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

    Records are kept in a ``deque`` ordered by insertion time.  Records older
    than *max_age_seconds* are pruned to prevent unbounded memory growth.

    **Single-process only.**  Each process maintains an independent ledger.
    Use for single-process services, local development, and tests.
    For production deployments use a custom ``SpendStore`` backed by
    PostgreSQL, Redis, or another shared store with DB-level atomic operations.

    Atomicity
    ---------
    ``check_and_record()`` acquires the internal lock for the entire
    read-decide-write sequence, making it atomic within a single process.
    ``get_spend()`` + ``record_spend()`` called separately are *not* atomic
    and may overshoot the cap under concurrent load.

    Args:
        max_age_seconds: Records older than this are eligible for pruning.
            Defaults to 7 days (604 800 s).
    """

    def __init__(self, max_age_seconds: int | None = None) -> None:
        # Default retention: 31 days (covers the longest possible calendar
        # month).  Callers can override for shorter windows.  The previous
        # default of 7 days (604 800 s) silently broke ``fixed month`` budgets
        # by pruning records before the month ended, causing undercounting
        # and budget overshoot after day 8.
        self._max_age_seconds = max_age_seconds if max_age_seconds is not None else 2_678_400
        self._records: deque[_SpendRecord] = deque()
        self._lock = Lock()

    # ------------------------------------------------------------------
    # SpendStore protocol implementation
    # ------------------------------------------------------------------

    def record_spend(
        self,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a spend event at the current wall-clock time."""
        if amount <= Decimal("0"):
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
        start: float,
        end: float | None = None,
        scope: dict[str, str] | None = None,
    ) -> Decimal:
        """Sum all spend for *currency* in the time range [start, end]."""
        with self._lock:
            return self._sum_locked(currency, start, end, scope)

    def check_and_record(
        self,
        amount: Decimal,
        currency: str,
        limit: Decimal,
        start: float,
        end: float | None = None,
        scope: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, Decimal]:
        """Atomically check the period budget and record if within limit.

        Acquires the internal lock for the entire read-decide-write sequence.
        **Single-process atomicity only** — does not coordinate across
        multiple processes or replicas.
        """
        if amount <= Decimal("0"):
            raise ValueError(f"amount must be positive, got {amount!r}")

        now = time.time()
        with self._lock:
            current = self._sum_locked(currency, start, end, scope)
            if current + amount > limit:
                return False, current
            record = _SpendRecord(
                amount=amount,
                currency=currency,
                recorded_at=now,
                metadata=metadata,
            )
            self._records.append(record)
            self._prune_locked(now)
            return True, current

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sum_locked(
        self,
        currency: str,
        start: float,
        end: float | None,
        scope: dict[str, str] | None,
    ) -> Decimal:
        """Sum records matching the query (must be called with _lock held)."""
        total = Decimal("0")
        for r in self._records:
            if r.currency != currency:
                continue
            if r.recorded_at < start:
                continue
            if end is not None and r.recorded_at > end:
                continue
            if scope is not None and not r.matches_scope(scope):
                continue
            total += r.amount
        return total

    def _prune_locked(self, now: float) -> None:
        """Remove records older than *max_age_seconds* (called with lock held)."""
        cutoff = now - self._max_age_seconds
        while self._records and self._records[0].recorded_at < cutoff:
            self._records.popleft()

    def record_count(self) -> int:
        """Return the current number of stored records (useful for tests)."""
        with self._lock:
            return len(self._records)
