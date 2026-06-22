"""Regex rule for pattern matching."""

from typing import Any

import re2
from agent_control_models import RuleResult

from agent_control_rules._base import Rule, RuleMetadata
from agent_control_rules._registry import register_rule
from agent_control_rules.regex.config import RegexRuleConfig


@register_rule
class RegexRule(Rule[RegexRuleConfig]):
    """Regular expression pattern matching rule.

    Matches data against a regex pattern using Google RE2 for safety
    (protects against ReDoS attacks).

    Supported flags:
        - IGNORECASE / I: Case-insensitive matching

    Example config:
        {"pattern": "\\\\d{3}-\\\\d{2}-\\\\d{4}"}  # SSN pattern
        {"pattern": "secret", "flags": ["IGNORECASE"]}  # Case-insensitive
    """

    metadata = RuleMetadata(
        name="regex",
        version="1.0.0",
        description="Regular expression pattern matching (RE2)",
    )
    config_model = RegexRuleConfig

    def __init__(self, config: RegexRuleConfig) -> None:
        super().__init__(config)
        # Build pattern with flags
        pattern = config.pattern
        if config.flags:
            # RE2 supports inline flags via (?i) prefix for case-insensitive
            for flag in config.flags:
                flag_upper = flag.upper()
                if flag_upper in ("IGNORECASE", "I"):
                    pattern = f"(?i){pattern}"
                # RE2 has limited flag support - other flags are ignored
        self._regex = re2.compile(pattern)

    async def evaluate(self, data: Any) -> RuleResult:
        """Evaluate data against the regex pattern.

        Args:
            data: Data to match against (will be converted to string)

        Returns:
            RuleResult with matched=True if pattern found
        """
        if data is None:
            return RuleResult(
                matched=False,
                confidence=1.0,
                message="No data to match",
            )

        text = str(data)
        match = self._regex.search(text)
        is_match = match is not None

        return RuleResult(
            matched=is_match,
            confidence=1.0,
            message=f"Pattern '{self.config.pattern}' {'found' if is_match else 'not found'}",
            metadata={"pattern": self.config.pattern},
        )
