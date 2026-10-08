"""Configuration model for direct Galileo LLM-as-judge scorer evaluation."""

from __future__ import annotations

import os
from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from agent_control_models import JSONValue
from pydantic import BaseModel, ConfigDict, Field, model_validator

LlmOperator = Literal["gt", "gte", "lt", "lte", "eq", "ne", "contains", "any"]
LlmPayloadField = Literal["input", "output"]

_NUMERIC_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})
LLM_INVOKE_RUNTIME_FLAG_ENV = "GALILEO_FEATURE_FLAG_LLM_INVOKE_RUNTIME"


def llm_invoke_runtime_enabled() -> bool:
    """Return whether the LLM scorer invoke runtime is enabled.

    The LLM evaluator requires Orbit support for ``execution_context`` to fetch
    LLM credentials. Set ``GALILEO_FEATURE_FLAG_LLM_INVOKE_RUNTIME=enabled`` once
    the Orbit-side support is confirmed ready.
    """
    return os.getenv(LLM_INVOKE_RUNTIME_FLAG_ENV) == "enabled"


class ScorerInvokeConfig(BaseModel):
    """Orbit-supported overrides for a synchronous scorer invocation.

    Orbit owns the Galileo scorer-invoke wire contract. Keeping this model
    strict makes an unsupported option fail locally instead of producing a
    less actionable HTTP 422 response from Runners.

    Attributes:
        request_timeout_seconds: Optional upper bound for scorer execution in
            Orbit. The Agent Control HTTP and evaluator deadlines must remain
            longer than this value.
    """

    model_config = ConfigDict(extra="forbid")

    request_timeout_seconds: float | None = Field(default=None, gt=0)


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


class LlmEvaluatorConfig(EvaluatorConfig):
    """Configuration for direct LLM-as-judge scorer evaluation.

    Attributes:
        scorer_id: Required scorer identifier for LLM scorer invocation.
        scorer_version_id: Optional. When absent, contextual evaluation sends
            legacy inputs only and skips the structured record.
        scorer_label: Optional display/metadata label.
        threshold: Local threshold used by the evaluator for comparison.
        operator: Local comparison operator. Numeric operators use threshold as a number.
        scorer_config: Optional Orbit-supported scorer invocation config sent
            as ``config``.
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
        description=(
            "Optional. When absent, contextual evaluation sends legacy inputs only "
            "and skips the structured record."
        ),
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
    operator: LlmOperator = Field(
        default="gte",
        description="Local comparison operator applied to the raw LLM scorer score.",
    )
    scorer_config: ScorerInvokeConfig | None = Field(
        default=None,
        alias="config",
        serialization_alias="config",
        description=(
            "Optional Orbit-supported configuration sent to the LLM scorer invoke endpoint."
        ),
    )
    payload_field: LlmPayloadField = Field(
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
