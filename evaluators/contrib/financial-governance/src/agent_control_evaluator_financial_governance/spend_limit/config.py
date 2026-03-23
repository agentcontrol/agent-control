"""Configuration model for the spend-limit evaluator."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator, model_validator

from agent_control_evaluators import EvaluatorConfig


class BudgetWindow(EvaluatorConfig):
    """Defines the time window for a rolling or calendar-based budget.

    Attributes:
        kind: ``"rolling"`` — a sliding window of *seconds* duration;
              ``"fixed"`` — a calendar-aligned window (day / week / month).
        seconds: Window length in seconds.  **Required** when ``kind="rolling"``.
        unit: Calendar unit.  **Required** when ``kind="fixed"``.
            One of ``"day"``, ``"week"``, ``"month"``.
        timezone: IANA timezone name for ``kind="fixed"`` windows (e.g.
            ``"America/New_York"``).  Defaults to ``"UTC"`` when omitted.

    Examples::

        BudgetWindow(kind="rolling", seconds=86400)          # 24-hour rolling
        BudgetWindow(kind="fixed", unit="day")               # UTC calendar day
        BudgetWindow(kind="fixed", unit="month", timezone="America/New_York")
    """

    kind: str = Field(
        ...,
        description='Window kind: "rolling" or "fixed".',
    )
    seconds: int | None = Field(
        default=None,
        ge=1,
        description="Window duration in seconds.  Required for kind='rolling'.",
    )
    unit: str | None = Field(
        default=None,
        description=(
            'Calendar unit: "day", "week", or "month".  Required for kind="fixed".'
        ),
    )
    timezone: str | None = Field(
        default=None,
        description='IANA timezone (e.g. "America/New_York").  Defaults to "UTC".',
    )

    @model_validator(mode="after")
    def validate_window_fields(self) -> BudgetWindow:
        """Enforce that required fields are present for each kind."""
        if self.kind == "rolling":
            if self.seconds is None:
                raise ValueError(
                    "BudgetWindow kind='rolling' requires 'seconds' to be set"
                )
        elif self.kind == "fixed":
            valid_units = {"day", "week", "month"}
            if self.unit is None:
                raise ValueError(
                    "BudgetWindow kind='fixed' requires 'unit' to be set "
                    f"(one of {sorted(valid_units)})"
                )
            if self.unit not in valid_units:
                raise ValueError(
                    f"BudgetWindow unit must be one of {sorted(valid_units)}, "
                    f"got '{self.unit}'"
                )
        else:
            raise ValueError(
                f"BudgetWindow kind must be 'rolling' or 'fixed', got '{self.kind}'"
            )
        return self


class BudgetLimit(EvaluatorConfig):
    """A single budget constraint, optionally scoped to a context dimension.

    Attributes:
        amount: Maximum monetary amount.  Uses ``Decimal`` for precision —
            never ``float`` for money.
        currency: Currency symbol this limit applies to (e.g. ``"USDC"``).
        scope_by: Tuple of context dimension keys used to isolate budgets.
            Each dimension is **independent**: ``scope_by=("channel",)`` creates
            a separate counter for each unique channel value.
            An empty tuple means global (unscoped): all transactions for this
            currency share a single counter.
        window: Time window for accumulated-spend budgets.  ``None`` means a
            per-transaction cap: ``amount`` is the maximum for any single
            transaction, regardless of accumulated spend.

    Examples::

        # Per-transaction cap of 500 USDC regardless of channel or agent
        BudgetLimit(amount=Decimal("500"), currency="USDC")

        # Per-channel rolling 24-hour budget of 5000 USDC
        BudgetLimit(
            amount=Decimal("5000"),
            currency="USDC",
            scope_by=("channel",),
            window=BudgetWindow(kind="rolling", seconds=86400),
        )

        # Per-agent calendar-day budget (US Eastern)
        BudgetLimit(
            amount=Decimal("1000"),
            currency="USDC",
            scope_by=("agent_id",),
            window=BudgetWindow(kind="fixed", unit="day", timezone="America/New_York"),
        )
    """

    amount: Decimal = Field(
        ...,
        gt=Decimal("0"),
        description="Budget ceiling — Decimal for monetary precision.",
    )
    currency: str = Field(
        ...,
        min_length=1,
        description="Currency symbol this limit applies to (e.g. 'USDC', 'ETH').",
    )
    scope_by: tuple[str, ...] = Field(
        default=(),
        description=(
            "Context dimension keys that isolate spend buckets. "
            "scope_by=('channel',) → one budget per channel. "
            "Empty tuple = global budget."
        ),
    )
    window: BudgetWindow | None = Field(
        default=None,
        description=(
            "Time window for accumulated-spend budgets. "
            "None = per-transaction cap (amount is the per-call maximum)."
        ),
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Normalize currency symbol to upper-case for consistent comparison."""
        return v.upper()

    @field_validator("scope_by", mode="before")
    @classmethod
    def coerce_scope_by(cls, v: Any) -> tuple[str, ...]:
        """Accept list or tuple for scope_by and coerce to tuple."""
        if isinstance(v, list):
            return tuple(v)
        return v


class SpendLimitConfig(EvaluatorConfig):
    """Configuration for :class:`~.evaluator.SpendLimitEvaluator`.

    Each entry in *limits* is evaluated independently.  First violation wins.

    Attributes:
        limits: List of :class:`BudgetLimit` constraints to enforce.
            The evaluator checks each limit in order and returns a violation
            result on the first breach.  An empty list means no limits —
            all transactions are allowed.

    Example config dict::

        {
          "limits": [
            {"amount": "500.00", "currency": "USDC"},
            {
              "amount": "5000.00",
              "currency": "USDC",
              "scope_by": ["channel"],
              "window": {"kind": "rolling", "seconds": 86400}
            }
          ]
        }
    """

    limits: list[BudgetLimit] = Field(
        default_factory=list,
        description="Budget constraints to enforce. Evaluated in order; first violation wins.",
    )
