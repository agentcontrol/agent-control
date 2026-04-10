"""Configuration model for the transaction-policy evaluator."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from agent_control_evaluators import EvaluatorConfig
from pydantic import Field, field_validator, model_validator


class TransactionPolicyConfig(EvaluatorConfig):
    """Configuration for :class:`~.evaluator.TransactionPolicyEvaluator`.

    All list fields default to empty lists (no restriction applied).  A field
    is only enforced when it contains at least one entry.

    Attributes:
        allowed_recipients: If non-empty, **only** recipients in this list are
            permitted.  Transactions to any other address are blocked.
        blocked_recipients: Recipients that are explicitly prohibited.  Checked
            before ``allowed_recipients``.
        min_amount: Minimum transaction amount (inclusive).  ``Decimal("0")``
            disables the lower bound check.
        max_amount: Maximum transaction amount (inclusive).  ``Decimal("0")``
            disables the upper bound check.
        allowed_currencies: If non-empty, **only** currencies in this list are
            permitted.

    Example config dict::

        {
          "allowed_recipients": ["0xABC...", "0xDEF..."],
          "blocked_recipients": ["0xDEAD..."],
          "min_amount": "0.01",
          "max_amount": "10000.00",
          "allowed_currencies": ["USDC", "USDT"]
        }
    """

    allowed_recipients: list[str] = Field(
        default_factory=list,
        description=(
            "Allowlisted recipient addresses. When non-empty, only these "
            "recipients are permitted."
        ),
    )
    blocked_recipients: list[str] = Field(
        default_factory=list,
        description="Blocklisted recipient addresses that are always denied.",
    )
    min_amount: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description="Minimum transaction amount (inclusive). Decimal('0') = no minimum.",
    )
    max_amount: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description="Maximum transaction amount (inclusive). Decimal('0') = no maximum.",
    )
    allowed_currencies: list[str] = Field(
        default_factory=list,
        description=(
            "Permitted currency symbols. When non-empty, only these "
            "currencies are accepted."
        ),
    )

    @field_validator("allowed_currencies", mode="before")
    @classmethod
    def normalize_currencies(cls, v: Any) -> list[str]:
        """Normalize all currency symbols to upper-case."""
        if not isinstance(v, list):
            return v
        return [c.upper() for c in v]

    @model_validator(mode="after")
    def validate_amount_bounds(self) -> TransactionPolicyConfig:
        """Ensure max_amount >= min_amount when both are non-zero."""
        if (
            self.max_amount > Decimal("0")
            and self.min_amount > Decimal("0")
            and self.max_amount < self.min_amount
        ):
            raise ValueError(
                f"max_amount ({self.max_amount}) must be >= min_amount ({self.min_amount})"
            )
        return self
