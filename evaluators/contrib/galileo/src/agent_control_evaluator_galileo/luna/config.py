"""Configuration model for direct Galileo Luna scorer evaluation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

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
        project_id: Optional Galileo project UUID for project-scoped scorer resolution.
        threshold: Local threshold used by the evaluator for comparison.
        operator: Local comparison operator. Numeric operators use threshold as a number.
        scorer_config: Optional scorer-specific config sent as ``config``.
        timeout_ms: Request timeout in milliseconds.
        on_error: Error policy: allow=fail open, deny=fail closed.
        payload_field: Force selected data into input or output. If omitted, root step
            payloads with input/output use both fields; scalar data is inferred from scorer label.
        include_raw_response: Include the raw API response in EvaluatorResult metadata.
    """

    scorer_label: str = Field(..., min_length=1, description="Luna scorer label to invoke")
    project_id: UUID | None = Field(
        default=None,
        description="Optional Galileo project UUID for project-scoped scorer resolution.",
    )
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
    on_error: Literal["allow", "deny"] = Field(
        default="allow",
        description="Action on error: 'allow' (fail open) or 'deny' (fail closed)",
    )
    payload_field: Literal["input", "output"] | None = Field(
        default=None,
        description="Explicitly set which scorer payload field receives scalar selected data.",
    )
    include_raw_response: bool = Field(
        default=False,
        description="Include the raw scorer response in result metadata.",
    )

    @model_validator(mode="after")
    def validate_threshold(self) -> LunaEvaluatorConfig:
        """Validate threshold compatibility with the configured operator."""
        if self.operator in _NUMERIC_OPERATORS and coerce_number(self.threshold) is None:
            raise ValueError(f"operator '{self.operator}' requires a numeric threshold")
        if self.operator != "any" and self.threshold is None:
            raise ValueError("threshold is required unless operator is 'any'")
        return self
