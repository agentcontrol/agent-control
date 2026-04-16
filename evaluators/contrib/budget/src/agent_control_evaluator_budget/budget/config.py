"""Configuration for the budget evaluator."""

from __future__ import annotations

from typing import Literal

from agent_control_evaluators._base import EvaluatorConfig
from pydantic import Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Window convenience constants (seconds)
# ---------------------------------------------------------------------------

WINDOW_HOURLY = 3600
WINDOW_DAILY = 86400
WINDOW_WEEKLY = 604800
WINDOW_MONTHLY = 2592000  # 30 days


class ModelPricing(EvaluatorConfig):
    """Per-model token pricing in cents per 1K tokens."""

    input_per_1k: float = 0.0
    output_per_1k: float = 0.0


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
        limit: Maximum usage in the window. Interpreted by limit_unit.
        limit_unit: Unit for limit. usd_cents checks spend; tokens checks
            input + output tokens.
    """

    scope: dict[str, str] = Field(default_factory=dict)
    group_by: str | None = None
    window_seconds: int | None = None
    limit: int
    limit_unit: Literal["usd_cents", "tokens"] = "usd_cents"

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("limit must be a positive integer")
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
        budget_id: Unique budget pool identifier. Same budget_id shares
            accumulated spend. Different budget_id is fully isolated.
        unknown_model_behavior: What to do when a model is not found in the
            pricing table and a cost-based rule exists. block=fail closed,
            warn=log warning and treat cost as 0.
        pricing: Optional model pricing table. Maps model name to ModelPricing.
            Used to derive cost in USD from token counts and model name.
        token_path: Dot-notation path to extract token usage from step
            data (e.g. "usage.total_tokens"). If None, looks for standard
            fields (input_tokens, output_tokens, total_tokens, usage).
        model_path: Dot-notation path to extract model name (for pricing lookup).
        metadata_paths: Mapping of metadata field name to dot-notation path
            in step data. Used to extract scope dimensions (channel, user_id, etc).
    """

    limits: list[BudgetLimitRule] = Field(min_length=1)
    budget_id: str = Field(
        default="default",
        description=(
            "Unique budget pool identifier. Same budget_id shares accumulated spend. "
            "Different budget_id is fully isolated."
        ),
    )
    unknown_model_behavior: Literal["block", "warn"] = Field(
        default="block",
        description=(
            "What to do when a model is not found in the pricing table and a cost-based "
            "rule exists. block=fail closed, warn=log warning and treat cost as 0."
        ),
    )
    pricing: dict[str, ModelPricing] | None = None
    token_path: str | None = None
    model_path: str | None = None
    metadata_paths: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_pricing_for_cost_rules(self) -> "BudgetEvaluatorConfig":
        has_cost_rule = any(rule.limit_unit == "usd_cents" for rule in self.limits)
        if has_cost_rule and self.pricing is None:
            raise ValueError('pricing is required when any rule uses limit_unit="usd_cents"')
        if has_cost_rule and not (self.model_path or "").strip():
            raise ValueError('model_path is required when any rule uses limit_unit="usd_cents"')
        return self
