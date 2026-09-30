"""Configuration model for direct Galileo LLM-as-judge scorer evaluation."""

from __future__ import annotations

from agent_control_evaluators import EvaluatorConfig
from agent_control_models import JSONValue
from pydantic import Field, model_validator

from agent_control_evaluator_galileo._shared.config import (
    ScorerOperator,
    ScorerPayloadField,
    _NUMERIC_OPERATORS,
    coerce_number,
)


class LlmEvaluatorConfig(EvaluatorConfig):
    """Configuration for direct LLM-as-judge scorer evaluation.

    Attributes:
        scorer_id: Required scorer identifier for LLM scorer invocation.
        scorer_version_id: Optional pinned scorer version identifier.
        scorer_label: Optional display/metadata label.
        threshold: Local threshold used by the evaluator for comparison.
        operator: Local comparison operator. Numeric operators use threshold as a number.
        payload_field: Explicit scorer input side for scalar selected data.
        timeout_ms: Request timeout in milliseconds.
    """

    scorer_id: str = Field(
        min_length=1,
        description="Required scorer identifier for LLM scorer invocation.",
    )
    scorer_version_id: str | None = Field(
        default=None,
        min_length=1,
        description="Optional pinned scorer version identifier.",
    )
    scorer_label: str | None = Field(
        default=None,
        min_length=1,
        description="Optional display/metadata label.",
    )
    threshold: JSONValue = Field(
        default=0.5,
        description="Local threshold used to decide whether the control matches.",
    )
    operator: ScorerOperator = Field(
        default="gte",
        description="Local comparison operator applied to the raw LLM scorer score.",
    )
    payload_field: ScorerPayloadField = Field(
        default="input",
        description=(
            "Which scorer input side to use when selector output is a scalar value. "
            "Structured selected data with input/output keys overrides this setting."
        ),
    )
    timeout_ms: int = Field(
        default=10000,
        ge=1000,
        le=60000,
        description="Request timeout in milliseconds (1-60 seconds)",
    )

    @model_validator(mode="after")
    def validate_threshold(self) -> LlmEvaluatorConfig:
        """Validate threshold compatibility with the configured operator."""
        if self.operator in _NUMERIC_OPERATORS and coerce_number(self.threshold) is None:
            raise ValueError(f"operator '{self.operator}' requires a numeric threshold")
        if self.operator != "any" and self.threshold is None:
            raise ValueError("threshold is required unless operator is 'any'")
        return self
