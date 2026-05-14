"""Configuration model for direct Galileo Luna scorer evaluation."""

from __future__ import annotations

from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from agent_control_models import JSONObject, JSONValue
from pydantic import Field, model_validator

LunaOperator = Literal["gt", "gte", "lt", "lte", "eq", "ne", "contains", "any"]

_NUMERIC_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})


def coerce_number(value: JSONValue) -> float | None:
    """Return a numeric value for JSON scalars that can be compared numerically."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


class LunaEvaluatorConfig(EvaluatorConfig):
    """Configuration for direct Luna scorer evaluation.

    Attributes:
        scorer_label: Preset, registered, or fine-tuned scorer label.
        threshold: Local threshold used by the evaluator for comparison.
        operator: Local comparison operator. Numeric operators use threshold as a number.
        scorer_config: Optional scorer-specific config sent as ``config``.
        timeout_ms: Request timeout in milliseconds.
    """

    scorer_label: str = Field(..., min_length=1, description="Luna scorer label to invoke")
    threshold: JSONValue = Field(
        default=0.5,
        description="Local threshold used to decide whether the control matches.",
    )
    operator: LunaOperator = Field(
        default="gte",
        description="Local comparison operator applied to the raw Luna score.",
    )
    scorer_config: JSONObject | None = Field(
        default=None,
        alias="config",
        serialization_alias="config",
        description="Optional scorer-specific configuration sent to Galileo.",
    )
    timeout_ms: int = Field(
        default=10000,
        ge=1000,
        le=60000,
        description="Request timeout in milliseconds (1-60 seconds)",
    )

    @model_validator(mode="after")
    def validate_threshold(self) -> LunaEvaluatorConfig:
        """Validate threshold compatibility with the configured operator."""
        if self.operator in _NUMERIC_OPERATORS and coerce_number(self.threshold) is None:
            raise ValueError(f"operator '{self.operator}' requires a numeric threshold")
        if self.operator != "any" and self.threshold is None:
            raise ValueError("threshold is required unless operator is 'any'")
        return self
