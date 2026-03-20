"""Spend-limit evaluator — tracks cumulative agent spend against rolling budgets."""

from __future__ import annotations

import time
from typing import Any

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .config import SpendLimitConfig
from .store import InMemorySpendStore, SpendStore


def _extract_float(data: dict[str, Any], key: str) -> float | None:
    """Safely extract a float value from *data* by *key*."""
    raw = data.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@register_evaluator
class SpendLimitEvaluator(Evaluator[SpendLimitConfig]):
    """Evaluator that enforces per-transaction and rolling-period spend limits.

    ``matched=True`` means the transaction **violates** the configured limits
    and should be blocked.  ``matched=False`` means the transaction is within
    budget and may proceed.

    Thread safety:
        The evaluator itself is stateless.  All mutable state lives in the
        injected :class:`~.store.SpendStore`.  The default
        :class:`~.store.InMemorySpendStore` is thread-safe.

    Instance caching note:
        Evaluator instances are cached and reused across requests (see base
        class docstring).  Only the ``SpendStore`` instance is mutable; do not
        add per-request state to ``self``.

    Evaluating context-aware limits:
        The ``data`` dict may contain channel-specific override keys such as
        ``channel_max_per_transaction`` or ``channel_max_per_period``.  These
        override the base config values for that call, implementing lan17's
        requirement that rules take context/metadata into account.

    Args:
        config: Validated :class:`SpendLimitConfig`.
        store: Optional :class:`SpendStore` implementation.  Defaults to a new
            :class:`InMemorySpendStore` when not provided.

    Input ``data`` schema::

        {
          "amount":     float,   # required — transaction amount
          "currency":   str,     # required — payment currency
          "recipient":  str,     # required — recipient address or identifier
          # optional context fields
          "channel":    str,
          "agent_id":   str,
          "session_id": str,
          # optional per-call limit overrides (from evaluate() metadata)
          "channel_max_per_transaction": float,
          "channel_max_per_period":      float
        }

    Example::

        from agent_control_evaluator_financial_governance.spend_limit import (
            SpendLimitConfig,
            SpendLimitEvaluator,
        )

        config = SpendLimitConfig(
            max_per_transaction=100.0,
            max_per_period=1000.0,
            period_seconds=86400,
            currency="USDC",
        )
        evaluator = SpendLimitEvaluator(config)
        result = await evaluator.evaluate({
            "amount": 50.0,
            "currency": "USDC",
            "recipient": "0xABC...",
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
            # Merge step context into tx so downstream logic sees channel/agent_id
            merged = {**tx}
            if isinstance(ctx, dict):
                for k in ("channel", "agent_id", "session_id"):
                    if k in ctx and k not in merged:
                        merged[k] = ctx[k]
                # Support context-level limit overrides
                for k in ("channel_max_per_transaction", "channel_max_per_period"):
                    if k in ctx and k not in merged:
                        merged[k] = ctx[k]
            return merged, ctx if isinstance(ctx, dict) else {}

        # Otherwise assume data IS the transaction dict (selector.path: "input")
        return data, {}

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate a transaction against configured spend limits.

        Args:
            data: Transaction dict (when ``selector.path`` is ``"input"``)
                or full Step dict (when path is ``"*"``).  Transaction fields:
                ``amount``, ``currency``, ``recipient``.  Context fields
                (``channel``, ``agent_id``, ``session_id``) can live in the
                transaction dict or in ``step.context``.

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
                    f"Could not extract transaction data from selector output; "
                    "skipping spend-limit check"
                ),
            )

        # Replace data with normalized transaction dict for the rest of evaluate
        data = tx_data

        # ---- Extract required fields ----
        # NOTE: Malformed selector output is NOT an evaluator error.  The
        # ``error`` field is reserved for evaluator crashes / timeouts /
        # missing dependencies.  Missing or invalid fields in the data dict
        # are normal "does not match" results.
        amount = _extract_float(data, "amount")
        if amount is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Transaction data missing required field 'amount'; cannot evaluate",
            )
        if amount <= 0:
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

        # ---- Currency filter — only enforce policy for configured currency ----
        if tx_currency != self.config.currency:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message=(
                    f"Transaction currency '{tx_currency}' does not match policy "
                    f"currency '{self.config.currency}'; skipping"
                ),
                metadata={"tx_currency": tx_currency, "policy_currency": self.config.currency},
            )

        # ---- Resolve effective limits (context/metadata overrides) ----
        # Callers can embed channel-specific overrides directly in the data dict.
        # This satisfies lan17's guidance that rules take context/metadata into account.
        effective_max_per_tx = _extract_float(data, "channel_max_per_transaction")
        if effective_max_per_tx is None:
            effective_max_per_tx = self.config.max_per_transaction

        effective_max_per_period = _extract_float(data, "channel_max_per_period")
        if effective_max_per_period is None:
            effective_max_per_period = self.config.max_per_period

        # ---- Per-transaction cap ----
        if effective_max_per_tx > 0 and amount > effective_max_per_tx:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=(
                    f"Transaction amount {amount} {tx_currency} exceeds per-transaction "
                    f"cap of {effective_max_per_tx} {tx_currency}"
                ),
                metadata={
                    "violation": "per_transaction_cap",
                    "amount": amount,
                    "max_per_transaction": effective_max_per_tx,
                    "currency": tx_currency,
                    "recipient": recipient,
                },
            )

        # ---- Rolling period budget ----
        if effective_max_per_period > 0:
            since = time.time() - self.config.period_seconds

            # Build scope for context-aware budget isolation.
            # When channel/agent/session overrides are present, query only
            # spend matching that context — not global spend.
            scope: dict[str, str] | None = None
            if any(k in data for k in ("channel", "agent_id", "session_id")):
                scope = {
                    k: str(data[k])
                    for k in ("channel", "agent_id", "session_id")
                    if k in data and data[k] is not None
                }
                if not scope:
                    scope = None

            period_spend = self._store.get_spend(tx_currency, since, scope=scope)
            projected = period_spend + amount

            if projected > effective_max_per_period:
                return EvaluatorResult(
                    matched=True,
                    confidence=1.0,
                    message=(
                        f"Transaction would bring period spend to "
                        f"{projected:.4f} {tx_currency}, exceeding the "
                        f"{self.config.period_seconds}s budget of "
                        f"{effective_max_per_period} {tx_currency} "
                        f"(current period spend: {period_spend:.4f})"
                    ),
                    metadata={
                        "violation": "period_budget",
                        "amount": amount,
                        "current_period_spend": period_spend,
                        "projected_period_spend": projected,
                        "max_per_period": effective_max_per_period,
                        "period_seconds": self.config.period_seconds,
                        "currency": tx_currency,
                        "recipient": recipient,
                    },
                )

        # ---- Transaction is within limits — record it ----
        spend_metadata: dict[str, Any] = {
            k: data[k]
            for k in ("channel", "agent_id", "session_id")
            if k in data and data[k] is not None
        }
        spend_metadata["recipient"] = recipient

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
                "amount": amount,
                "currency": tx_currency,
                "recipient": recipient,
            },
        )
