"""Tests for list evaluator."""

import pytest
from pydantic import ValidationError

from agent_control_evaluators.list import ListEvaluator, ListEvaluatorConfig


class TestListEvaluatorConfig:
    """Tests for list evaluator config validation."""

    def test_empty_string_value_rejected(self) -> None:
        """Test that empty-string list entries are rejected at config validation time."""
        # Given: a list evaluator config with an empty-string value
        # When: constructing the config model
        with pytest.raises(
            ValidationError, match="values must not contain empty or whitespace-only strings"
        ):
            ListEvaluatorConfig(values=[""])
        # Then: validation rejects the config (asserted by pytest)

    def test_whitespace_only_value_rejected(self) -> None:
        """Test that whitespace-only list entries are rejected at config validation time."""
        # Given: a list evaluator config with a whitespace-only value
        # When: constructing the config model
        with pytest.raises(
            ValidationError, match="values must not contain empty or whitespace-only strings"
        ):
            ListEvaluatorConfig(values=[" "])
        # Then: validation rejects the config (asserted by pytest)


class TestListEvaluator:
    """Tests for list evaluator runtime behavior."""

    @pytest.mark.asyncio
    async def test_starts_with_matches_prefix(self) -> None:
        """Test that starts_with mode triggers on prefix matches."""
        # Given: a starts_with evaluator config
        evaluator = ListEvaluator(
            ListEvaluatorConfig(
                values=["/home/lev/agent-control", "/tmp/cache"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a path under an allowed prefix
        result = await evaluator.evaluate("/home/lev/agent-control/server/src/app.py")

        # Then: the prefix match triggers
        assert result.matched is True
        assert result.metadata["matches"] == ["/home/lev/agent-control/server/src/app.py"]

    @pytest.mark.asyncio
    async def test_starts_with_no_match_when_prefix_absent(self) -> None:
        """Test that starts_with mode does not trigger when no prefix matches."""
        # Given: a starts_with evaluator config
        evaluator = ListEvaluator(
            ListEvaluatorConfig(
                values=["/home/lev/agent-control", "/tmp/cache"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating a path with no configured prefix
        result = await evaluator.evaluate("/var/log/system.log")

        # Then: the evaluator does not trigger
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_starts_with_honors_case_sensitivity(self) -> None:
        """Test that starts_with mode respects case sensitivity settings."""
        # Given: two starts_with evaluators that differ only by case sensitivity
        insensitive = ListEvaluator(
            ListEvaluatorConfig(
                values=["/HOME/LEV/AGENT-CONTROL"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=False,
            )
        )
        sensitive = ListEvaluator(
            ListEvaluatorConfig(
                values=["/HOME/LEV/AGENT-CONTROL"],
                logic="any",
                match_on="match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating the same lower-case path against both
        insensitive_result = await insensitive.evaluate("/home/lev/agent-control/server")
        sensitive_result = await sensitive.evaluate("/home/lev/agent-control/server")

        # Then: only the case-insensitive evaluator matches
        assert insensitive_result.matched is True
        assert sensitive_result.matched is False

    @pytest.mark.asyncio
    async def test_starts_with_supports_no_match_allowlists(self) -> None:
        """Test that starts_with works with no_match for allowlist-style controls."""
        # Given: a starts_with evaluator configured as an allowlist
        evaluator = ListEvaluator(
            ListEvaluatorConfig(
                values=["/home/lev/agent-control", "/tmp/cache"],
                logic="any",
                match_on="no_match",
                match_mode="starts_with",
                case_sensitive=True,
            )
        )

        # When: evaluating one allowed and one disallowed path
        allowed_result = await evaluator.evaluate("/home/lev/agent-control/server")
        denied_result = await evaluator.evaluate("/var/log/system.log")

        # Then: only the disallowed path triggers the control
        assert allowed_result.matched is False
        assert denied_result.matched is True

    @pytest.mark.asyncio
    async def test_legacy_empty_string_value_is_ignored_defensively(self) -> None:
        """Test that legacy invalid configs do not compile into a match-all regex."""
        # Given: a legacy invalid config constructed without validation
        config = ListEvaluatorConfig.model_construct(
            values=[""],
            logic="any",
            match_on="match",
            match_mode="contains",
            case_sensitive=False,
        )
        evaluator = ListEvaluator(config)

        # When: evaluating normal text against the legacy config
        result = await evaluator.evaluate("Tell me a joke")

        # Then: the evaluator ignores the empty control values
        assert result.matched is False
        assert result.message == "Empty control values - control ignored"

    @pytest.mark.asyncio
    async def test_legacy_whitespace_only_value_is_ignored_defensively(self) -> None:
        """Test that legacy whitespace-only configs do not compile into pathological regexes."""
        # Given: a legacy invalid config with a whitespace-only value
        config = ListEvaluatorConfig.model_construct(
            values=[" "],
            logic="any",
            match_on="match",
            match_mode="contains",
            case_sensitive=False,
        )
        evaluator = ListEvaluator(config)

        # When: evaluating normal text against the legacy config
        result = await evaluator.evaluate("Tell me a joke")

        # Then: the evaluator ignores the empty control values
        assert result.matched is False
        assert result.message == "Empty control values - control ignored"

    @pytest.mark.asyncio
    async def test_legacy_empty_string_allowlist_does_not_block_all(self) -> None:
        """Test that legacy invalid allowlist configs do not block all inputs."""
        # Given: a legacy invalid allowlist config constructed without validation
        config = ListEvaluatorConfig.model_construct(
            values=[""],
            logic="any",
            match_on="no_match",
            match_mode="contains",
            case_sensitive=False,
        )
        evaluator = ListEvaluator(config)

        # When: evaluating normal text against the legacy config
        result = await evaluator.evaluate("legitimate_value")

        # Then: the evaluator ignores the empty control values instead of blocking all input
        assert result.matched is False
        assert result.message == "Empty control values - control ignored"
