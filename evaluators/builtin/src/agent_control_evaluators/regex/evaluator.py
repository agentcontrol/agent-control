"""Regex evaluator for pattern matching."""

from typing import Any

import re2
from agent_control_models import EvaluatorResult

from agent_control_evaluators._base import Evaluator, EvaluatorMetadata
from agent_control_evaluators._registry import register_evaluator
from agent_control_evaluators.regex.config import RegexEvaluatorConfig


@register_evaluator
class RegexEvaluator(Evaluator[RegexEvaluatorConfig]):
    """Regular expression pattern matching evaluator.

    Matches data against a regex pattern using Google RE2 for safety
    (protects against ReDoS attacks).

    Supported flags:
        - IGNORECASE / I: Case-insensitive matching

    Example config:
        {"pattern": "\\\\d{3}-\\\\d{2}-\\\\d{4}"}  # SSN pattern
        {"pattern": "secret", "flags": ["IGNORECASE"]}  # Case-insensitive
    """

    metadata = EvaluatorMetadata(
        name="regex",
        version="1.0.0",
        description="Regular expression pattern matching (RE2)",
    )
    config_model = RegexEvaluatorConfig

    def __init__(self, config: RegexEvaluatorConfig) -> None:
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

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate data against the regex pattern.

        Args:
            data: Data to match against (will be converted to string)

        Returns:
            EvaluatorResult with matched=True if pattern found
        """
        if data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No data to match",
            )

        text = str(data)
        match = self._regex.search(text)
        is_match = match is not None

        return EvaluatorResult(
            matched=is_match,
            confidence=1.0,
            message=f"Pattern '{self.config.pattern}' {'found' if is_match else 'not found'}",
            metadata={"pattern": self.config.pattern},
        )
