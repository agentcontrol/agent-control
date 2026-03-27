"""Evaluation-related models."""
from typing import Literal

from pydantic import Field, field_validator

from .agent import AGENT_NAME_MIN_LENGTH, AGENT_NAME_PATTERN, Step, normalize_agent_name
from .base import BaseModel
from .controls import ControlMatch


class EvaluationRequest(BaseModel):
    """
    Request model for evaluation analysis.

    Used to analyze agent interactions for safety violations,
    policy compliance, and control rules.

    Attributes:
        agent_name: Unique identifier of the agent making the request
        step: Step payload for evaluation
        stage: 'pre' (before execution) or 'post' (after execution)
    """
    agent_name: str = Field(
        ...,
        min_length=AGENT_NAME_MIN_LENGTH,
        pattern=AGENT_NAME_PATTERN,
        description="Identifier of the agent making the evaluation request",
    )
    step: Step = Field(
        ..., description="Agent step payload to evaluate"
    )
    stage: Literal["pre", "post"] = Field(
        ..., description="Evaluation stage: 'pre' or 'post'"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "agent_name": "customer-service-bot",
                    "step": {
                        "type": "llm",
                        "name": "support-answer",
                        "input": "What is the customer's credit card number?",
                        "context": {"user_id": "user123", "session_id": "abc123"},
                    },
                    "stage": "pre"
                },
                {
                    "agent_name": "customer-service-bot",
                    "step": {
                        "type": "llm",
                        "name": "support-answer",
                        "input": "What is the customer's credit card number?",
                        "output": "I cannot share sensitive payment information.",
                        "context": {"user_id": "user123", "session_id": "abc123"},
                    },
                    "stage": "post"
                },
                {
                    "agent_name": "customer-service-bot",
                    "step": {
                        "type": "tool",
                        "name": "search_database",
                        "input": {"query": "SELECT * FROM users"},
                        "context": {"user_id": "user123"},
                    },
                    "stage": "pre"
                },
                {
                    "agent_name": "customer-service-bot",
                    "step": {
                        "type": "tool",
                        "name": "search_database",
                        "input": {"query": "SELECT * FROM users"},
                        "output": {"results": []},
                        "context": {"user_id": "user123"},
                    },
                    "stage": "post"
                }
            ]
        }
    }

    @field_validator("agent_name", mode="before")
    @classmethod
    def validate_and_normalize_agent_name(cls, value: str) -> str:
        return normalize_agent_name(str(value))


class EvaluationResponse(BaseModel):
    """
    Response model from evaluation analysis (server-side).

    This is what the server returns. The SDK may transform this
    into an EvaluationResult for client convenience.

    Attributes:
        is_safe: Whether the content is considered safe
        confidence: Confidence score between 0.0 and 1.0
        reason: Optional explanation for the decision
        matches: List of controls that matched/triggered (if any)
        errors: List of controls that failed during evaluation (if any)
        non_matches: List of controls that were evaluated but did not match (if any)
    """

    is_safe: bool = Field(..., description="Whether content is safe")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0 to 1.0)",
    )
    reason: str | None = Field(
        default=None,
        description="Explanation for the decision",
    )
    matches: list[ControlMatch] | None = Field(
        default=None,
        description="List of controls that matched/triggered (if any)",
    )
    errors: list[ControlMatch] | None = Field(
        default=None,
        description="List of controls that failed during evaluation (if any)",
    )
    non_matches: list[ControlMatch] | None = Field(
        default=None,
        description="List of controls that were evaluated but did not match (if any)",
    )
class EvaluationResult(EvaluationResponse):
    """
    Client-side result model for evaluation analysis.

    Extends EvaluationResponse with additional client-side convenience methods.
    This is what SDK users interact with.
    """

    def is_confident(self, threshold: float = 0.8) -> bool:
        """
        Check if the result confidence exceeds a threshold.

        Args:
            threshold: Minimum confidence threshold (default: 0.8)

        Returns:
            True if confidence >= threshold
        """
        return self.confidence >= threshold

    def __bool__(self) -> bool:
        """
        Allow boolean evaluation of result.

        Returns:
            True if content is safe, False otherwise
        """
        return self.is_safe

    def __str__(self) -> str:
        """
        String representation of the result.

        Returns:
            Human-readable description
        """
        status = "SAFE" if self.is_safe else "UNSAFE"
        conf_pct = int(self.confidence * 100)
        base = f"[{status}] Confidence: {conf_pct}%"
        if self.reason:
            return f"{base} - {self.reason}"
        return base
