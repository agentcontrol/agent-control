"""List evaluator for value matching."""

import re
from typing import Any

import re2
from agent_control_models import EvaluatorResult

from agent_control_evaluators._base import Evaluator, EvaluatorMetadata
from agent_control_evaluators._registry import register_evaluator
from agent_control_evaluators.list.config import ListEvaluatorConfig


@register_evaluator
class ListEvaluator(Evaluator[ListEvaluatorConfig]):
    """List-based value matching evaluator.

    Checks if data matches values in a list. Supports:
    - any/all logic (match any value vs match all values)
    - match/no_match trigger (trigger on match or no match)
    - exact/contains mode (full match vs substring/keyword)
    - case sensitivity toggle

    Example configs:
        {"values": ["admin", "root"], "logic": "any"}  # Block admin/root
        {"values": ["approved"], "match_on": "no_match"}  # Require approval
    """

    metadata = EvaluatorMetadata(
        name="list",
        version="1.0.0",
        description="List-based value matching with flexible logic",
    )
    config_model = ListEvaluatorConfig

    def __init__(self, config: ListEvaluatorConfig) -> None:
        super().__init__(config)
        self._values = [str(v) for v in config.values]
        self._regex: Any = self._build_regex()

    def _build_regex(self) -> Any:
        """Build regex pattern for matching."""
        if not self._values:
            return None

        escaped = [re.escape(v) for v in self._values]

        if self.config.match_mode == "contains":
            # Word boundary matching for substring/keyword detection
            pattern = f"\\b({'|'.join(escaped)})\\b"
        else:
            # Exact match using anchors
            pattern = f"^({'|'.join(escaped)})$"

        if not self.config.case_sensitive:
            pattern = f"(?i){pattern}"

        return re2.compile(pattern)

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate data against the value list.

        Args:
            data: Data to check (string or list of strings)

        Returns:
            EvaluatorResult based on matching logic
        """
        # Normalize input
        if data is None:
            input_values: list[str] = []
        elif isinstance(data, list):
            input_values = [str(item) for item in data]
        else:
            input_values = [str(data)]

        # Short-circuit if input is empty
        if not input_values:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Empty input - control ignored",
                metadata={"input_count": 0},
            )

        # Short-circuit if control values are empty
        if self._regex is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Empty control values - control ignored",
                metadata={"input_count": len(input_values)},
            )

        # Perform matching
        matches = [val for val in input_values if self._regex.search(val)]
        match_count = len(matches)
        total_count = len(input_values)

        # Determine if logic condition is met
        if self.config.logic == "any":
            condition_met = match_count > 0
        else:  # all
            condition_met = match_count == total_count

        # Apply match_on inversion
        is_match = condition_met
        if self.config.match_on == "no_match":
            is_match = not condition_met

        # Build message
        if is_match:
            msg = "Control triggered."
        else:
            msg = "Control not triggered."
        msg += f" Logic: {self.config.logic}, MatchOn: {self.config.match_on}."
        if matches:
            msg += f" Matched: {', '.join(matches[:5])}"  # Limit to 5
            if len(matches) > 5:
                msg += f" (+{len(matches) - 5} more)"

        return EvaluatorResult(
            matched=is_match,
            confidence=1.0,
            message=msg,
            metadata={
                "logic": self.config.logic,
                "match_on": self.config.match_on,
                "matches": matches,
                "input_count": total_count,
            },
        )
