"""List rule for value matching."""

import re
from typing import Any

import re2
from agent_control_models import RuleResult

from agent_control_rules._base import Rule, RuleMetadata
from agent_control_rules._registry import register_rule
from agent_control_rules.list.config import ListRuleConfig


@register_rule
class ListRule(Rule[ListRuleConfig]):
    """List-based value matching rule.

    Checks if data matches values in a list. Supports:
    - any/all logic (match any value vs match all values)
    - match/no_match trigger (trigger on match or no match)
    - exact/contains/starts_with/ends_with mode (full match vs keyword vs prefix/suffix)
    - case sensitivity toggle

    Example configs:
        {"values": ["admin", "root"], "logic": "any"}  # Block admin/root
        {"values": ["approved"], "match_on": "no_match"}  # Require approval
    """

    metadata = RuleMetadata(
        name="list",
        version="1.0.0",
        description="List-based value matching with flexible logic",
    )
    config_model = ListRuleConfig

    def __init__(self, config: ListRuleConfig) -> None:
        super().__init__(config)
        # Defensive filtering keeps legacy invalid configs from compiling into pathological regexes.
        normalized_values = [str(v) for v in config.values]
        self._values = [value for value in normalized_values if value.strip() != ""]
        self._regex: Any = self._build_regex()

    def _build_regex(self) -> Any:
        """Build regex pattern for matching."""
        if not self._values:
            return None

        escaped = [re.escape(v) for v in self._values]

        if self.config.match_mode == "contains":
            # Word boundary matching for substring/keyword detection
            pattern = f"\\b({'|'.join(escaped)})\\b"
        elif self.config.match_mode == "starts_with":
            # Prefix matching using anchors
            pattern = f"^({'|'.join(escaped)})"
        elif self.config.match_mode == "ends_with":
            # Suffix matching using anchors
            pattern = f"({'|'.join(escaped)})$"
        else:
            # Exact match using anchors
            pattern = f"^({'|'.join(escaped)})$"

        if not self.config.case_sensitive:
            pattern = f"(?i){pattern}"

        return re2.compile(pattern)

    async def evaluate(self, data: Any) -> RuleResult:
        """Evaluate data against the value list.

        Args:
            data: Data to check (string or list of strings)

        Returns:
            RuleResult based on matching logic
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
            return RuleResult(
                matched=False,
                confidence=1.0,
                message="Empty input - control ignored",
                metadata={"input_count": 0},
            )

        # Short-circuit if control values are empty
        if self._regex is None:
            return RuleResult(
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

        return RuleResult(
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
