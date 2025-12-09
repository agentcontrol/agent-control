"""Regex plugin for pattern matching."""

from typing import Any

import re2
from agent_control_models import (
    EvaluatorResult,
    PluginEvaluator,
    PluginMetadata,
    RegexConfig,
    register_plugin,
)


@register_plugin
class RegexPlugin(PluginEvaluator[RegexConfig]):
    """Regular expression pattern matching plugin.

    Matches data against a regex pattern using Google RE2 for safety
    (protects against ReDoS attacks).

    Example config:
        {"pattern": "\\\\d{3}-\\\\d{2}-\\\\d{4}"}  # SSN pattern
    """

    metadata = PluginMetadata(
        name="regex",
        version="1.0.0",
        description="Regular expression pattern matching (RE2)",
    )
    config_model = RegexConfig

    def __init__(self, config: RegexConfig) -> None:
        super().__init__(config)
        # Pre-compile regex for efficiency
        self._regex = re2.compile(config.pattern)

    def evaluate(self, data: Any) -> EvaluatorResult:
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
