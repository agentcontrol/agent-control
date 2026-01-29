"""Evaluation-related models."""
from typing import Literal
from uuid import UUID

from pydantic import Field

from .agent import Step
from .base import BaseModel
from .controls import ControlMatch


class EvaluationRequest(BaseModel):
    """
    Request model for evaluation analysis.

    Used to analyze agent interactions for safety violations,
    policy compliance, and control rules.

    Attributes:
        agent_uuid: UUID of the agent making the request
        step: Step payload for evaluation
        stage: 'pre' (before execution) or 'post' (after execution)
    """
    agent_uuid: UUID = Field(
        ..., description="UUID of the agent making the evaluation request"
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
                    "agent_uuid": "550e8400-e29b-41d4-a716-446655440000",
                    "step": {
                        "type": "llm",
                        "name": "support-answer",
                        "input": "What is the customer's credit card number?",
                        "context": {"user_id": "user123", "session_id": "abc123"},
                    },
                    "stage": "pre"
                },
                {
                    "agent_uuid": "550e8400-e29b-41d4-a716-446655440000",
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
                    "agent_uuid": "550e8400-e29b-41d4-a716-446655440000",
                    "step": {
                        "type": "tool",
                        "name": "search_database",
                        "input": {"query": "SELECT * FROM users"},
                        "context": {"user_id": "user123"},
                    },
                    "stage": "pre"
                },
                {
                    "agent_uuid": "550e8400-e29b-41d4-a716-446655440000",
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
