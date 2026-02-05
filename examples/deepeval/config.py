"""Configuration models for DeepEval GEval evaluator.

Based on DeepEval's GEval metric: https://deepeval.com/docs/metrics-llm-evals
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# DeepEval's LLMTestCaseParams enum values
DeepEvalTestCaseParam = Literal[
    "input",
    "actual_output",
    "expected_output",
    "context",
    "retrieval_context",
    "tools_called",
    "expected_tools",
    "mcp_servers",
    "mcp_tools_called",
    "mcp_resources_called",
    "mcp_prompts_called",
]


class DeepEvalEvaluatorConfig(BaseModel):
    """Configuration for DeepEval GEval evaluator.

    DeepEval's GEval uses LLM-as-a-judge with chain-of-thoughts (CoT) to evaluate
    LLM outputs based on custom criteria. It's capable of evaluating almost any
    use case with human-like accuracy.

    Example (with criteria):
        ```python
        config = DeepEvalEvaluatorConfig(
            name="Correctness",
            criteria="Determine if the actual output is correct based on the expected output.",
            evaluation_params=["actual_output", "expected_output"],
            threshold=0.5,
        )
        ```

    Example (with evaluation_steps):
        ```python
        config = DeepEvalEvaluatorConfig(
            name="Correctness",
            evaluation_steps=[
                "Check whether facts in actual output contradict expected output",
                "Heavily penalize omission of detail",
                "Vague language or contradicting opinions are acceptable"
            ],
            evaluation_params=["actual_output", "expected_output"],
            threshold=0.5,
        )
        ```
    """

    name: str = Field(
        description="Name identifier for the custom metric (e.g., 'Correctness', 'Relevance')"
    )

    criteria: str | None = Field(
        default=None,
        description="Description outlining the specific evaluation aspects. Either provide criteria OR evaluation_steps, not both.",
    )

    evaluation_steps: list[str] | None = Field(
        default=None,
        description="Specific steps the LLM should follow during evaluation. If omitted with criteria, will be auto-generated. Either provide criteria OR evaluation_steps, not both.",
    )

    evaluation_params: list[DeepEvalTestCaseParam] = Field(
        description="List of test case parameters to include in evaluation (e.g., ['input', 'actual_output'])"
    )

    threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Passing threshold (0-1). Metric is successful if score >= threshold.",
    )

    model: str = Field(
        default="gpt-4o",
        description="GPT model to use for evaluation (e.g., 'gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo')",
    )

    strict_mode: bool = Field(
        default=False,
        description="If True, enforces binary scoring (0 or 1). If False, returns scores in 0-1 range.",
    )

    async_mode: bool = Field(
        default=True,
        description="Enable concurrent execution for better performance.",
    )

    verbose_mode: bool = Field(
        default=False,
        description="Print intermediate calculation steps for debugging.",
    )

    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Request timeout in milliseconds (1-120 seconds)",
    )

    on_error: Literal["allow", "deny"] = Field(
        default="allow",
        description="Action on error: 'allow' (fail open) or 'deny' (fail closed)",
    )

    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata for logging/tracking",
    )

    @model_validator(mode="after")
    def validate_criteria_or_steps(self) -> "DeepEvalEvaluatorConfig":
        """Validate that either criteria or evaluation_steps is provided, but not both."""
        has_criteria = self.criteria is not None
        has_steps = self.evaluation_steps is not None and len(self.evaluation_steps) > 0

        if not has_criteria and not has_steps:
            raise ValueError(
                "Either 'criteria' or 'evaluation_steps' must be provided"
            )

        if has_criteria and has_steps:
            raise ValueError(
                "Provide either 'criteria' OR 'evaluation_steps', not both. "
                "If you provide criteria, evaluation_steps will be auto-generated."
            )

        return self
