"""Configuration models for LangSmith evaluator."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Supported LangSmith metrics
LangSmithMetric = Literal[
    "toxicity",
    "relevance",
    "accuracy",
    "hallucination",
    "coherence",
    "pii_detection",
    "custom",
]


class LangSmithEvaluatorConfig(BaseModel):
    """Configuration for LangSmith evaluator.

    This evaluator uses LangSmith's evaluation APIs to assess agent outputs
    for various quality and safety metrics.

    Example (toxicity check):
        ```python
        config = LangSmithEvaluatorConfig(
            metric="toxicity",
            threshold=0.8,
            langsmith_project="my-project",
        )
        ```

    Example (relevance check with context):
        ```python
        config = LangSmithEvaluatorConfig(
            metric="relevance",
            threshold=0.7,
            langsmith_project="my-project",
            require_context=True,
        )
        ```

    Example (custom evaluator):
        ```python
        config = LangSmithEvaluatorConfig(
            metric="custom",
            custom_evaluator_name="my-custom-evaluator",
            threshold=0.5,
            langsmith_project="my-project",
        )
        ```
    """

    metric: LangSmithMetric = Field(
        description="LangSmith metric to evaluate"
    )

    threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Threshold for triggering control (0.0-1.0). Scores above this trigger a denial.",
    )

    langsmith_project: str | None = Field(
        default=None,
        description="LangSmith project name for logging and organization",
    )

    custom_evaluator_name: str | None = Field(
        default=None,
        description="Name of custom evaluator (required if metric='custom')",
    )

    require_context: bool = Field(
        default=False,
        description="Whether the evaluation requires additional context (for relevance/accuracy checks)",
    )

    context_key: str = Field(
        default="context",
        description="Key to look for context in the data (e.g., 'context', 'documents')",
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

    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata to include with evaluations",
    )

    @model_validator(mode="after")
    def validate_custom_evaluator(self) -> "LangSmithEvaluatorConfig":
        """Validate that custom evaluator name is provided when using custom metric."""
        if self.metric == "custom" and not self.custom_evaluator_name:
            raise ValueError("'custom_evaluator_name' is required when metric='custom'")
        return self
