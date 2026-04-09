from __future__ import annotations

from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from pydantic import Field


class ATRConfig(EvaluatorConfig):
    """Configuration for ATR (Agent Threat Rules) evaluator.

    Attributes:
        min_severity: Minimum severity level to match ("low", "medium", "high", "critical")
        block_on_match: Whether to set matched=True when a threat is detected
        categories: Category filter; empty list means all categories
        on_error: Error policy ("allow" = fail-open, "deny" = fail-closed)
    """

    min_severity: Literal["low", "medium", "high", "critical"] = "medium"
    block_on_match: bool = True
    categories: list[str] = Field(default_factory=list)
    on_error: Literal["allow", "deny"] = "allow"
