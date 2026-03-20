"""Configuration model for the spend-limit evaluator."""

from __future__ import annotations

from pydantic import Field, field_validator

from agent_control_evaluators import EvaluatorConfig


class SpendLimitConfig(EvaluatorConfig):
    """Configuration for :class:`~.evaluator.SpendLimitEvaluator`.

    All monetary fields are expressed in the units of *currency*.

    Attributes:
        max_per_transaction: Hard cap on any single transaction amount.  A
            transaction whose ``amount`` exceeds this value is blocked
            regardless of accumulated period spend.  Set to ``0.0`` to disable.
        max_per_period: Maximum total spend allowed within the rolling
            *period_seconds* window.  Set to ``0.0`` to disable.
        period_seconds: Length of the rolling budget window in seconds.
            Defaults to ``86400`` (24 hours).
        currency: Currency symbol this policy applies to (e.g. ``"USDC"``).
            Transactions whose currency does not match are passed through as
            *not matched* (i.e. allowed).

    Example config dict::

        {
          "max_per_transaction": 500.0,
          "max_per_period": 5000.0,
          "period_seconds": 86400,
          "currency": "USDC"
        }
    """

    max_per_transaction: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Per-transaction spend cap in *currency* units. "
            "0.0 means no per-transaction limit."
        ),
    )
    max_per_period: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Maximum cumulative spend allowed in the rolling period window. "
            "0.0 means no period limit."
        ),
    )
    period_seconds: int = Field(
        default=86_400,
        ge=1,
        description="Rolling budget window length in seconds (default: 86400 = 24 h).",
    )
    currency: str = Field(
        ...,
        min_length=1,
        description="Currency symbol this policy applies to (e.g. 'USDC', 'ETH').",
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Normalize currency symbol to upper-case for consistent comparison."""
        return v.upper()
