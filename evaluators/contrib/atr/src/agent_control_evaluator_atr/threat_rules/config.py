from __future__ import annotations

from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from pydantic import Field


class ATRConfig(EvaluatorConfig):
    """Configuration for ATR (Agent Threat Rules) evaluator.

    Attributes:
        min_severity: Minimum severity level to match ("low", "medium", "high", "critical").
        block_on_match: Whether to set matched=True when a threat is detected.
        categories: Category filter; empty list means all categories.
        on_error: Error policy ("allow" = fail-open, "deny" = fail-closed).
        condition_budget_ms: Wall-clock budget for each regex condition evaluation,
            in milliseconds. Patterns exceeding this budget are skipped with a
            warning rather than blocking the evaluator pipeline. Default 50 ms
            is generous for any reasonable pattern; the budget only fires on
            catastrophic backtracking.
    """

    min_severity: Literal["low", "medium", "high", "critical"] = "medium"
    block_on_match: bool = True
    categories: list[str] = Field(default_factory=list)
    on_error: Literal["allow", "deny"] = "allow"
    condition_budget_ms: int = Field(default=50, ge=1, le=10_000)
