"""Configuration for a single reviewed, local Quarry rule."""

from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from pydantic import ConfigDict, Field, field_validator

type SessionMode = Literal["per_trace", "continuous"]


class QuarryEvaluatorConfig(EvaluatorConfig):
    """Compile one symbolic rule; require an explicit boundary choice for sessions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str = Field(min_length=1, description="Source of exactly one local Quarry DSL rule")
    session_mode: SessionMode | None = Field(
        default=None,
        description="Required for sessions: independent traces, or one ordered conversation",
    )
    timeout_ms: int = Field(default=10000, ge=1, le=300000, strict=True)
    max_messages: int = Field(default=10000, ge=1, le=10000, strict=True)

    @field_validator("rule")
    @classmethod
    def nonblank_rule(cls, value: str) -> str:
        """Reject whitespace without changing the reviewed rule source."""
        if not value.strip():
            raise ValueError("rule must contain Quarry DSL source")
        return value
