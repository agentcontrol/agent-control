"""Configuration models for Luna-2 evaluator."""

from typing import Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

# Supported Luna-2 metrics
Luna2Metric = Literal[
    "input_toxicity",
    "output_toxicity",
    "input_sexism",
    "output_sexism",
    "prompt_injection",
    "pii_detection",
    "hallucination",
    "tone",
]

# Supported operators
Luna2Operator = Literal["gt", "lt", "gte", "lte", "eq", "contains", "any"]


class Luna2EvaluatorConfig(BaseModel):
    """Configuration for Luna-2 evaluator.

    Two stage types are supported:
    - local: Define rules at runtime (requires metric, operator, target_value)
    - central: Reference pre-defined stages in Galileo (requires stage_name)

    Example (local stage with numeric threshold - recommended):
        ```python
        config = Luna2EvaluatorConfig(
            stage_type="local",
            metric="input_toxicity",
            operator="gt",
            target_value=0.5,  # Use numeric for proper comparison
            galileo_project="my-project",
        )
        ```

    Example (central stage - recommended for production):
        ```python
        config = Luna2EvaluatorConfig(
            stage_type="central",
            stage_name="production-guard",
            galileo_project="my-project",
        )
        ```

    Note: For numeric comparisons (gt, lt, gte, lte), use numeric target_value
    (float/int) instead of strings for proper evaluation.
    """

    stage_type: Literal["local", "central"] = Field(
        default="local",
        description="Use 'local' for runtime rules or 'central' for pre-defined stages",
    )

    # Local stage fields
    metric: Luna2Metric | None = Field(
        default=None,
        description="Luna-2 metric to evaluate (required for local stage)",
    )
    operator: Luna2Operator | None = Field(
        default=None,
        description="Comparison operator (required for local stage)",
    )
    target_value: Union[str, float, int, None] = Field(
        default=None,
        description="Target value for comparison (required for local stage). Can be string or number.",
    )

    # Central stage fields
    stage_name: str | None = Field(
        default=None,
        description="Stage name in Galileo (required for central stage)",
    )
    stage_version: int | None = Field(
        default=None,
        description="Pin to specific stage version (optional)",
    )

    # Common fields
    galileo_project: str | None = Field(
        default=None,
        description="Galileo project name for logging/organization",
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
        description="Explicitly set which payload field to use",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata to send with the request",
    )

    @model_validator(mode="after")
    def validate_stage_config(self) -> "Luna2EvaluatorConfig":
        """Validate that required fields are present based on stage_type."""
        if self.stage_type == "local":
            if not self.metric:
                raise ValueError("'metric' is required for local stage")
            if not self.operator:
                raise ValueError("'operator' is required for local stage")
            if self.target_value is None:
                raise ValueError("'target_value' is required for local stage")
        elif self.stage_type == "central":
            if not self.stage_name:
                raise ValueError("'stage_name' is required for central stage")
        return self
