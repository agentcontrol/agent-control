"""Configuration for Galileo Decision Models scoring."""

from __future__ import annotations

import os
from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from agent_control_models import JSONValue
from pydantic import Field, model_validator

DecisionModelsOperator = Literal["gt", "gte", "lt", "lte", "eq", "ne", "contains", "any"]
DecisionModelsPayloadField = Literal["input", "output"]
_NUMERIC_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})
SCORER_INVOKE_RUNTIME_FLAG_ENV = "GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME"


def scorer_invoke_runtime_enabled() -> bool:
    """Return whether structured runtime data is enabled for Decision Models requests."""
    return os.getenv(SCORER_INVOKE_RUNTIME_FLAG_ENV) == "enabled"


class DecisionModelsEvaluatorConfig(EvaluatorConfig):
    """Pinned Decision Models scorer and local result comparison settings."""

    scorer_id: str = Field(min_length=1)
    scorer_version_id: str = Field(min_length=1)
    scorer_label: str | None = Field(default=None, min_length=1)
    threshold: JSONValue = 0.5
    operator: DecisionModelsOperator = "gte"
    payload_field: DecisionModelsPayloadField = Field(
        default="input",
        description="Record side to use when the selector returns a scalar value.",
    )
    timeout_ms: int = Field(default=10000, ge=1, le=60000)

    @model_validator(mode="after")
    def validate_threshold(self) -> DecisionModelsEvaluatorConfig:
        """Ensure ordered comparisons use a numeric threshold."""
        if self.operator in _NUMERIC_OPERATORS and (
            isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float))
        ):
            raise ValueError(f"operator '{self.operator}' requires a numeric threshold")
        if self.operator != "any" and self.threshold is None:
            raise ValueError("threshold is required unless operator is 'any'")
        return self
