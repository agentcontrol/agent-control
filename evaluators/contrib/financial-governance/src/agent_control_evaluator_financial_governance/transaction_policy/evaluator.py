"""Transaction-policy evaluator — static policy checks with no state tracking."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .config import TransactionPolicyConfig


@register_evaluator
class TransactionPolicyEvaluator(Evaluator[TransactionPolicyConfig]):
    """Stateless evaluator for static transaction policy checks.

    Checks are applied in this order (first violation wins):

    1. Currency allowlist (if configured)
    2. Recipient blocklist
    3. Recipient allowlist (if configured)
    4. Minimum amount bound
    5. Maximum amount bound

    ``matched=True`` means the transaction **violates** the policy and should be
    blocked.  ``matched=False`` means the transaction passed all checks.

    Thread safety:
        This evaluator has no mutable instance state.  Concurrent calls to
        :meth:`evaluate` are safe.

    Input ``data`` schema::

        {
          "amount":    Decimal | float | str,  # required — transaction amount
          "currency":  str,                    # required — payment currency
          "recipient": str,                    # required — recipient address or id
          # optional context fields (logged in result metadata)
          "channel":   str,
          "agent_id":  str,
          "session_id": str
        }

    Example::

        from agent_control_evaluator_financial_governance.transaction_policy import (
            TransactionPolicyConfig,
            TransactionPolicyEvaluator,
        )
        from decimal import Decimal

        config = TransactionPolicyConfig(
            allowed_currencies=["USDC", "USDT"],
            blocked_recipients=["0xDEAD..."],
            max_amount=Decimal("5000"),
        )
        evaluator = TransactionPolicyEvaluator(config)
        result = await evaluator.evaluate({
            "amount": "100.00",
            "currency": "USDC",
            "recipient": "0xABC...",
        })
        # result.matched == False  → transaction passes all policy checks
    """

    metadata = EvaluatorMetadata(
        name="financial_governance.transaction_policy",
        version="0.1.0",
        description=(
            "Static transaction policy enforcement: recipient allowlists/blocklists, "
            "amount bounds, and currency restrictions.  No state tracking."
        ),
    )
    config_model = TransactionPolicyConfig

    @staticmethod
    def _normalize_data(data: Any) -> dict[str, Any] | None:
        """Extract transaction fields from selector output.

        Handles ``selector.path: "input"`` (data is the transaction dict)
        and ``selector.path: "*"`` (data is the full Step dict).
        """
        if not isinstance(data, dict):
            return None
        if "type" in data and "input" in data:
            tx = data.get("input")
            ctx = data.get("context") or {}
            if not isinstance(tx, dict):
                return None
            merged = {**tx}
            if isinstance(ctx, dict):
                for k in ("channel", "agent_id", "session_id"):
                    if k in ctx and k not in merged:
                        merged[k] = ctx[k]
            return merged
        return data

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate a transaction against the static policy.

        Args:
            data: Transaction dict (when ``selector.path`` is ``"input"``)
                or full Step dict (when path is ``"*"``).  Malformed payload
                returns ``matched=False, error=None`` — not an evaluator error.

        Returns:
            ``EvaluatorResult`` where ``matched=True`` indicates a policy
            violation (transaction should be denied).
        """
        if data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No transaction data provided; skipping policy check",
            )

        tx_data = self._normalize_data(data)
        if tx_data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Could not extract transaction data from selector output; skipping",
            )

        # Use normalized transaction dict for the rest of evaluate
        data = tx_data

        # ---- Extract and validate required fields ----
        # Malformed input → matched=False, error=None (not an evaluator crash)
        currency_raw = data.get("currency")
        if not currency_raw:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Transaction data missing required field 'currency'",
            )
        currency: str = str(currency_raw).upper()

        recipient_raw = data.get("recipient")
        if not recipient_raw:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Transaction data missing required field 'recipient'",
            )
        recipient: str = str(recipient_raw).strip()

        amount_raw = data.get("amount")
        if amount_raw is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Transaction data missing required field 'amount'",
            )
        try:
            amount = Decimal(str(amount_raw))
        except (TypeError, ValueError, InvalidOperation):
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message=f"Transaction 'amount' is not numeric: {amount_raw!r}",
            )

        # Build shared metadata for result context
        base_meta: dict[str, Any] = {
            "amount": str(amount),
            "currency": currency,
            "recipient": recipient,
        }
        for ctx_key in ("channel", "agent_id", "session_id"):
            if ctx_key in data and data[ctx_key] is not None:
                base_meta[ctx_key] = data[ctx_key]

        # ---- Check 1: Currency allowlist ----
        if self.config.allowed_currencies:
            if currency not in self.config.allowed_currencies:
                return EvaluatorResult(
                    matched=True,
                    confidence=1.0,
                    message=(
                        f"Currency '{currency}' is not in the allowed currencies list: "
                        f"{self.config.allowed_currencies}"
                    ),
                    metadata={
                        **base_meta,
                        "violation": "currency_not_allowed",
                        "allowed_currencies": self.config.allowed_currencies,
                    },
                )

        # ---- Check 2: Recipient blocklist ----
        if self.config.blocked_recipients and recipient in self.config.blocked_recipients:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=f"Recipient '{recipient}' is on the blocklist",
                metadata={
                    **base_meta,
                    "violation": "recipient_blocked",
                },
            )

        # ---- Check 3: Recipient allowlist ----
        if self.config.allowed_recipients:
            if recipient not in self.config.allowed_recipients:
                return EvaluatorResult(
                    matched=True,
                    confidence=1.0,
                    message=(
                        f"Recipient '{recipient}' is not in the allowed recipients list"
                    ),
                    metadata={
                        **base_meta,
                        "violation": "recipient_not_allowed",
                    },
                )

        # ---- Check 4: Minimum amount ----
        if self.config.min_amount > Decimal("0") and amount < self.config.min_amount:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=(
                    f"Transaction amount {amount} {currency} is below the minimum "
                    f"of {self.config.min_amount} {currency}"
                ),
                metadata={
                    **base_meta,
                    "violation": "amount_below_minimum",
                    "min_amount": str(self.config.min_amount),
                },
            )

        # ---- Check 5: Maximum amount ----
        if self.config.max_amount > Decimal("0") and amount > self.config.max_amount:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=(
                    f"Transaction amount {amount} {currency} exceeds the maximum "
                    f"of {self.config.max_amount} {currency}"
                ),
                metadata={
                    **base_meta,
                    "violation": "amount_exceeds_maximum",
                    "max_amount": str(self.config.max_amount),
                },
            )

        # ---- All checks passed ----
        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message=(
                f"Transaction of {amount} {currency} to '{recipient}' "
                "passed all policy checks"
            ),
            metadata=base_meta,
        )
