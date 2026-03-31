"""Configuration for the budget evaluator."""

from __future__ import annotations

from enum import Enum

from agent_control_evaluators._base import EvaluatorConfig
from pydantic import Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Window convenience constants (seconds)
# ---------------------------------------------------------------------------

WINDOW_HOURLY = 3600
WINDOW_DAILY = 86400
WINDOW_WEEKLY = 604800
WINDOW_MONTHLY = 2592000  # 30 days


class Currency(str, Enum):
    """Supported budget currencies."""

    USD = "usd"
    EUR = "eur"
    TOKENS = "tokens"


class BudgetLimitRule(EvaluatorConfig):
    """A single budget limit rule.

    Each rule defines a ceiling for a combination of scope dimensions
    and time window. Multiple rules can apply to the same step -- the
    evaluator checks all of them and triggers on the first breach.

    Attributes:
        scope: Static scope dimensions that must match for this rule
            to apply. Empty dict = global rule.
            Examples:
                {"agent": "summarizer"} -- per-agent limit
                {"agent": "summarizer", "channel": "slack"} -- agent+channel limit
        group_by: If set, the limit is applied independently for each
            unique value of this dimension. e.g. group_by="user_id" means
            each user gets their own budget. None = shared/global limit.
        window_seconds: Time window for accumulation in seconds.
            None = cumulative (no reset). See WINDOW_* constants.
        limit: Maximum spend in the window, in minor units (e.g. cents
            for USD). None = uncapped on this dimension.
        currency: Currency for the limit. Defaults to USD.
        limit_tokens: Maximum tokens in the window. None = uncapped.
    """

    scope: dict[str, str] = Field(default_factory=dict)
    group_by: str | None = None
    window_seconds: int | None = None
    limit: int | None = None
    currency: Currency = Currency.USD
    limit_tokens: int | None = None

    @model_validator(mode="after")
    def at_least_one_limit(self) -> "BudgetLimitRule":
        if self.limit is None and self.limit_tokens is None:
            raise ValueError("At least one of limit or limit_tokens must be set")
        return self

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("limit must be a positive integer")
        return v

    @field_validator("limit_tokens")
    @classmethod
    def validate_limit_tokens(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("limit_tokens must be positive")
        return v

    @field_validator("window_seconds")
    @classmethod
    def validate_window_seconds(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("window_seconds must be positive")
        return v


class BudgetEvaluatorConfig(EvaluatorConfig):
    """Configuration for the budget evaluator.

    Attributes:
        limits: List of budget limit rules. Each is checked independently.
        pricing: Optional model pricing table. Maps model name to per-1K
            token rates. Used to derive cost in USD from token counts and
            model name.
        token_path: Dot-notation path to extract token usage from step
            data (e.g. "usage.total_tokens"). If None, looks for standard
            fields (input_tokens, output_tokens, total_tokens, usage).
        model_path: Dot-notation path to extract model name (for pricing lookup).
        metadata_paths: Mapping of metadata field name to dot-notation path
            in step data. Used to extract scope dimensions (channel, user_id, etc).
    """

    limits: list[BudgetLimitRule] = Field(min_length=1)
    pricing: dict[str, dict[str, float]] | None = None
    token_path: str | None = None
    model_path: str | None = None
    metadata_paths: dict[str, str] = Field(default_factory=dict)
