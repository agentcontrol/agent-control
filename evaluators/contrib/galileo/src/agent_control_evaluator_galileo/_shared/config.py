"""Shared configuration types for Galileo scorer evaluators.

Used by both galileo.luna and galileo.llm evaluators. Neither subpackage
is guaranteed to be installed alongside the other, so all shared config
code lives here rather than in either evaluator's own module tree.
"""

from __future__ import annotations

from typing import Literal

from agent_control_models import JSONValue
from pydantic import BaseModel, ConfigDict, Field

ScorerOperator = Literal["gt", "gte", "lt", "lte", "eq", "ne", "contains", "any"]
ScorerPayloadField = Literal["input", "output"]

_NUMERIC_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})


class ScorerInvokeConfig(BaseModel):
    """Orbit-supported overrides for a synchronous scorer invocation.

    Orbit owns the Galileo scorer-invoke wire contract. Keeping this model
    strict makes an unsupported option fail locally instead of producing a
    less actionable HTTP 422 response from Runners.

    Attributes:
        threshold: Legacy threshold accepted by Orbit. Agent Control still
            applies its evaluator threshold locally.
        score_threshold: Legacy score threshold accepted by Orbit.
        request_timeout_seconds: Optional upper bound for scorer execution in
            Orbit. The Agent Control HTTP and evaluator deadlines must remain
            longer than this value.
    """

    model_config = ConfigDict(extra="forbid")

    threshold: float | None = None
    score_threshold: float | None = None
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
