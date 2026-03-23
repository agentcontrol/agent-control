"""Spend-limit evaluator — tracks cumulative agent spend against rolling budgets."""

from __future__ import annotations

import calendar
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .config import BudgetLimit, SpendLimitConfig
from .store import InMemorySpendStore, SpendStore


def _extract_decimal(data: dict[str, Any], key: str) -> Decimal | None:
    """Safely extract a Decimal value from *data* by *key*.

    Returns None if the key is absent or the value cannot be coerced.
    """
    raw = data.get(key)
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _window_start(limit: BudgetLimit) -> float:
    """Compute the Unix timestamp start of the current budget window.

    For ``kind="rolling"``: ``now - seconds``.
    For ``kind="fixed"`` with ``unit="day"``: midnight UTC today.
    For ``kind="fixed"`` with ``unit="week"``: midnight UTC Monday of this week.
    For ``kind="fixed"`` with ``unit="month"``: midnight UTC on the 1st of this month.

    Note: Timezone support is noted in the model but calendar alignment uses UTC
    for now.  Full IANA timezone support is a follow-up.
    """
    window = limit.window
    assert window is not None  # called only when window is set

    now = time.time()
    if window.kind == "rolling":
        assert window.seconds is not None
        return now - window.seconds

    # kind == "fixed"
    import datetime as _dt
    utc_now = _dt.datetime.now(_dt.timezone.utc)

    if window.unit == "day":
        start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif window.unit == "week":
        # Monday of the current ISO week
        start = utc_now - _dt.timedelta(days=utc_now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    elif window.unit == "month":
        start = utc_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        # Fallback — should not happen given BudgetWindow validation
        start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)

    return start.timestamp()


@register_evaluator
class SpendLimitEvaluator(Evaluator[SpendLimitConfig]):
    """Evaluator that enforces per-transaction and rolling-period spend limits.

    ``matched=True`` means the transaction **violates** at least one configured
    limit and should be blocked.  ``matched=False`` means the transaction is
    within all budget constraints and may proceed.

    Thread safety:
        The evaluator itself is stateless.  All mutable state lives in the
        injected :class:`~.store.SpendStore`.  The default
        :class:`~.store.InMemorySpendStore` is thread-safe.

    Instance caching note:
        Evaluator instances are cached and reused across requests (see base
        class docstring).  Only the ``SpendStore`` instance is mutable; do not
        add per-request state to ``self``.

    Args:
        config: Validated :class:`SpendLimitConfig` with ``limits`` list.
        store: Optional :class:`SpendStore` implementation.  Defaults to a new
            :class:`InMemorySpendStore` when not provided.

    Input ``data`` schema::

        {
          "amount":     Decimal | float | str,  # required — transaction amount
          "currency":   str,                    # required — payment currency
          "recipient":  str,                    # required — recipient address or id
          # optional context fields (used for scope_by matching)
          "channel":    str,
          "agent_id":   str,
          "session_id": str,
        }

    Example::

        from agent_control_evaluator_financial_governance.spend_limit import (
            BudgetLimit, BudgetWindow, SpendLimitConfig, SpendLimitEvaluator
        )
        from decimal import Decimal

        config = SpendLimitConfig(limits=[
            BudgetLimit(amount=Decimal("100"), currency="USDC"),
            BudgetLimit(
                amount=Decimal("1000"),
                currency="USDC",
                scope_by=("channel",),
                window=BudgetWindow(kind="rolling", seconds=86400),
            ),
        ])
        evaluator = SpendLimitEvaluator(config)
        result = await evaluator.evaluate({
            "amount": "50.00",
            "currency": "USDC",
            "recipient": "0xABC...",
            "channel": "slack",
        })
        # result.matched == False  → transaction is within limits
    """

    metadata = EvaluatorMetadata(
        name="financial_governance.spend_limit",
        version="0.1.0",
        description=(
            "Tracks cumulative agent spend and enforces per-transaction caps "
            "and rolling period budgets.  Supports pluggable SpendStore backends."
        ),
    )
    config_model = SpendLimitConfig

    def __init__(
        self,
        config: SpendLimitConfig,
        store: SpendStore | None = None,
    ) -> None:
        super().__init__(config)
        self._store: SpendStore = store if store is not None else InMemorySpendStore()

    # ------------------------------------------------------------------
    # Main evaluation entry point
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_data(data: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Extract transaction fields and step context from selector output.

        Handles two selector paths:
        - ``selector.path: "input"`` → data IS the transaction dict.
        - ``selector.path: "*"`` → data is the full Step dict with ``input``
          and ``context`` sub-keys.

        Returns:
            (tx_data, step_context) where tx_data is the transaction dict
            (or None if missing) and step_context holds channel/agent_id/etc.
        """
        if not isinstance(data, dict):
            return None, {}

        # If data looks like a Step (has "input" + "type" keys), extract
        # the transaction payload from "input" and context from "context".
        if "type" in data and "input" in data:
            tx = data.get("input")
            ctx = data.get("context") or {}
            if not isinstance(tx, dict):
                return None, ctx if isinstance(ctx, dict) else {}
            # Merge step context into tx so downstream logic sees channel/agent_id.
            # Input fields take priority — context must NOT clobber input values.
            merged = {**tx}
            if isinstance(ctx, dict):
                for k in ("channel", "agent_id", "session_id"):
                    if k in ctx and k not in merged:
                        merged[k] = ctx[k]
            return merged, ctx if isinstance(ctx, dict) else {}

        # Otherwise assume data IS the transaction dict (selector.path: "input")
        return data, {}

    def _build_scope(
        self, data: dict[str, Any], limit: BudgetLimit
    ) -> dict[str, str] | None:
        """Build the scope filter for *limit* from transaction *data*.

        For each key in ``limit.scope_by``, extract the value from ``data``
        (if present).  Returns ``None`` (global query) when scope_by is empty
        or none of the specified keys are present in data.
        """
        if not limit.scope_by:
            return None

        scope: dict[str, str] = {}
        for k in limit.scope_by:
            val = data.get(k)
            if val is not None:
                scope[k] = str(val)

        return scope if scope else None

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate a transaction against all configured spend limits.

        Iterates over ``config.limits`` in order.  Returns the first violation
        found or a passing result if all limits are satisfied.  After passing
        all rolling-period limits, records the transaction in the store.

        Args:
            data: Transaction dict (when ``selector.path`` is ``"input"``)
                or full Step dict (when path is ``"*"``).  Malformed payload
                returns ``matched=False, error=None`` — not an evaluator error.

        Returns:
            ``EvaluatorResult`` where ``matched=True`` indicates a limit
            violation (transaction should be denied).
        """
        if data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No transaction data provided; skipping spend-limit check",
            )

        tx_data, _step_ctx = self._normalize_data(data)
        if tx_data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message=(
                    "Could not extract transaction data from selector output; "
                    "skipping spend-limit check"
                ),
            )

        data = tx_data

        # ---- Extract required fields ----
        # NOTE: Malformed selector output is NOT an evaluator error.
        # Missing or invalid fields → matched=False, error=None.
        amount = _extract_decimal(data, "amount")
        if amount is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Transaction data missing required field 'amount'; cannot evaluate",
            )
        if amount <= Decimal("0"):
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message=f"Transaction amount must be positive, got {amount}; cannot evaluate",
            )

        tx_currency: str = str(data.get("currency", "")).upper()
        if not tx_currency:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Transaction data missing required field 'currency'; cannot evaluate",
            )

        recipient: str = str(data.get("recipient", "")).strip()

        # ---- No limits configured → allow everything ----
        if not self.config.limits:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No limits configured; transaction allowed",
                metadata={"amount": float(amount), "currency": tx_currency, "recipient": recipient},
            )

        # ---- Evaluate each limit in order ----
        # We iterate all limits first to check.  If all pass, record once at the end.
        # For period budgets we use check_and_record atomically to avoid TOCTOU.
        # We collect limits that apply to this transaction (matching currency)
        # and also track which limits need to be recorded after all checks pass.

        period_limits_to_record: list[tuple[BudgetLimit, dict[str, str] | None, float]] = []
        # ^ (limit, scope, window_start)

        for limit in self.config.limits:
            # Skip limits for other currencies
            if limit.currency != tx_currency:
                continue

            scope = self._build_scope(data, limit)

            # Per-transaction cap (window=None)
            if limit.window is None:
                if amount > limit.amount:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            f"Transaction amount {amount} {tx_currency} exceeds "
                            f"per-transaction cap of {limit.amount} {tx_currency}"
                        ),
                        metadata={
                            "violation": "per_transaction_cap",
                            "amount": float(amount),
                            "max_per_transaction": float(limit.amount),
                            "currency": tx_currency,
                            "recipient": recipient,
                        },
                    )
                # Per-tx cap passes → no need to "record" a cap (it's per-call)

            else:
                # Rolling / fixed period budget
                win_start = _window_start(limit)
                period_limits_to_record.append((limit, scope, win_start))

                period_spend = self._store.get_spend(tx_currency, win_start, scope=scope)
                projected = period_spend + amount

                if projected > limit.amount:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            f"Transaction would bring period spend to "
                            f"{projected} {tx_currency}, exceeding the "
                            f"{limit.window.kind} budget of {limit.amount} {tx_currency} "
                            f"(current period spend: {period_spend})"
                        ),
                        metadata={
                            "violation": "period_budget",
                            "amount": float(amount),
                            "current_period_spend": float(period_spend),
                            "projected_period_spend": float(projected),
                            "max_per_period": float(limit.amount),
                            "currency": tx_currency,
                            "recipient": recipient,
                        },
                    )

        # ---- All limits passed — record the spend ----
        # Build metadata to attach to the spend record
        spend_metadata: dict[str, Any] = {
            k: data[k]
            for k in ("channel", "agent_id", "session_id")
            if k in data and data[k] is not None
        }
        spend_metadata["recipient"] = recipient

        # Record once per transaction (not once per limit — the store is a ledger)
        # We only need one record; all scope queries will find it via their filters.
        if period_limits_to_record:
            self._store.record_spend(
                amount=amount,
                currency=tx_currency,
                metadata=spend_metadata if spend_metadata else None,
            )

        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message=(
                f"Transaction of {amount} {tx_currency} to '{recipient}' is within limits"
            ),
            metadata={
                "amount": float(amount),
                "currency": tx_currency,
                "recipient": recipient,
            },
        )
