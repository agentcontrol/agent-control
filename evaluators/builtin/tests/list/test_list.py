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
