"""Tests for the regex evaluator and its config validation."""

from __future__ import annotations

import pytest
from agent_control_evaluators.regex.config import RegexEvaluatorConfig
from agent_control_evaluators.regex.evaluator import RegexEvaluator


class TestRegexConfig:
    """Pattern validation rejects invalid RE2 syntax at config time."""

    def test_valid_pattern_accepted(self):
        config = RegexEvaluatorConfig(pattern=r"\d{3}-\d{2}-\d{4}")
        assert config.pattern == r"\d{3}-\d{2}-\d{4}"

    def test_empty_pattern_accepted(self):
        # Empty string is technically a valid RE2 pattern (matches everything).
        config = RegexEvaluatorConfig(pattern="")
        assert config.pattern == ""

    def test_invalid_pattern_rejected(self):
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            RegexEvaluatorConfig(pattern="[invalid(regex")

    def test_flags_default_to_none(self):
        config = RegexEvaluatorConfig(pattern=r"\d+")
        assert config.flags is None

    def test_flags_can_be_specified(self):
        config = RegexEvaluatorConfig(pattern="secret", flags=["IGNORECASE"])
        assert config.flags == ["IGNORECASE"]


class TestRegexEvaluator:
    """Pattern matching against arbitrary data."""

    @pytest.mark.asyncio
    async def test_match_returns_matched_true(self):
        evaluator = RegexEvaluator.from_dict({"pattern": r"\d{3}-\d{4}"})

        result = await evaluator.evaluate("call 555-1234 today")

        assert result.matched is True
        assert result.confidence == 1.0
        assert "found" in result.message
        assert result.metadata["pattern"] == r"\d{3}-\d{4}"

    @pytest.mark.asyncio
    async def test_no_match_returns_matched_false(self):
        evaluator = RegexEvaluator.from_dict({"pattern": r"\d{3}-\d{4}"})

        result = await evaluator.evaluate("no numbers here")

        assert result.matched is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_none_data_returns_no_data_message(self):
        evaluator = RegexEvaluator.from_dict({"pattern": r".*"})

        result = await evaluator.evaluate(None)

        assert result.matched is False
        assert result.message == "No data to match"

    @pytest.mark.asyncio
    async def test_non_string_data_is_coerced(self):
        """Non-string inputs are stringified before matching."""
        evaluator = RegexEvaluator.from_dict({"pattern": r"^42$"})

        result = await evaluator.evaluate(42)

        assert result.matched is True

    @pytest.mark.asyncio
    async def test_ignorecase_flag_short_form(self):
        """The ``I`` short form is treated the same as ``IGNORECASE``."""
        evaluator = RegexEvaluator.from_dict(
            {"pattern": "SECRET", "flags": ["I"]},
        )

        result = await evaluator.evaluate("the secret value")

        assert result.matched is True

    @pytest.mark.asyncio
    async def test_ignorecase_flag_long_form(self):
        evaluator = RegexEvaluator.from_dict(
            {"pattern": "secret", "flags": ["IGNORECASE"]},
        )

        result = await evaluator.evaluate("THE SECRET VALUE")

        assert result.matched is True

    @pytest.mark.asyncio
    async def test_unknown_flag_is_ignored(self):
        """RE2 supports a narrow flag set; unknown flag names must not raise."""
        evaluator = RegexEvaluator.from_dict(
            {"pattern": "x", "flags": ["MULTILINE"]},
        )

        result = await evaluator.evaluate("xyz")

        # Should still work — unknown flag is silently dropped, not an error.
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_case_sensitive_by_default(self):
        evaluator = RegexEvaluator.from_dict({"pattern": "Secret"})

        result = await evaluator.evaluate("the secret value")

        assert result.matched is False
