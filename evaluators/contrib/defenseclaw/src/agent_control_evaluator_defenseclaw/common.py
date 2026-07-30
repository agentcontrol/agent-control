"""Shared DefenseClaw evaluator types and runtime behavior."""

from __future__ import annotations

from typing import Annotated, Literal

from agent_control_models import EvaluatorResult
from pydantic import ConfigDict, StringConstraints

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

STRICT_PROVIDER_CONFIG = ConfigDict(extra="forbid")


def no_op_result() -> EvaluatorResult:
    """Return the intentional no-op evaluation result."""
    return EvaluatorResult(
        matched=False,
        confidence=1.0,
        message="DefenseClaw configuration accepted; evaluator execution is a no-op",
    )
