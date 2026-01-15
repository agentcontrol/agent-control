"""Tests for unified evaluator factory."""

import pytest
from agent_control_engine.evaluators import (
    clear_evaluator_cache,
    get_available_plugins,
    get_evaluator,
)
from agent_control_models import (
    EvaluatorConfig,
    RegexControlEvaluatorPluginConfig,
)
from agent_control_plugins import ListControlEvaluatorPlugin, RegexControlEvaluatorPlugin


class TestRegexControlEvaluatorPlugin:
    """Tests for the regex plugin via the evaluator factory."""

    @pytest.mark.asyncio
    async def test_basic_match(self):
        """Test regex matches SSN pattern."""
        # Given: A regex evaluator with SSN pattern
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        evaluator = get_evaluator(config)

        # When: Evaluating text containing SSN
        result = await evaluator.evaluate("My SSN is 123-45-6789")

        # Then: Should match with high confidence
        assert result.matched is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_no_match(self):
        """Test regex doesn't match when pattern not found."""
        # Given: A regex evaluator with SSN pattern
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        evaluator = get_evaluator(config)

        # When: Evaluating text without pattern
        result = await evaluator.evaluate("No numbers here")

        # Then: Should not match
        assert result.matched is False
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_non_string_input(self):
        """Test non-string input is converted to string."""
        # Given: A regex evaluator
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"123"})
        evaluator = get_evaluator(config)

        # When: Evaluating non-string input
        result = await evaluator.evaluate(12345)

        # Then: Should match after conversion
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_none_input(self):
        """Test handling of None input."""
        # Given: A regex evaluator
        config = EvaluatorConfig(plugin="regex", config={"pattern": r".*"})
        evaluator = get_evaluator(config)

        # When: Evaluating None
        result = await evaluator.evaluate(None)

        # Then: Should not match and return message
        assert result.matched is False
        assert result.message == "No data to match"

    def test_invalid_regex_pattern(self):
        """Test invalid regex pattern raises error."""
        # Given/When: Creating config with invalid pattern
        # Then: Should raise ValueError
        with pytest.raises(ValueError):
            RegexControlEvaluatorPluginConfig(pattern="[")

    @pytest.mark.asyncio
    async def test_empty_pattern_matches_everything(self):
        """Test empty pattern matches everything."""
        # Given: A regex evaluator with empty pattern
        config = EvaluatorConfig(plugin="regex", config={"pattern": ""})
        evaluator = get_evaluator(config)

        # When: Evaluating any text
        result = await evaluator.evaluate("something")

        # Then: Should match
        assert result.matched is True


class TestListControlEvaluatorPlugin:
    """Tests for the list plugin via the evaluator factory."""

    @pytest.mark.asyncio
    async def test_any_match(self):
        """Test list evaluator with any/match logic."""
        # Given: A list evaluator with blocklist items
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["bad", "evil"], "logic": "any", "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        # When/Then: Blocklist items match, others don't
        assert (await evaluator.evaluate("bad")).matched is True
        assert (await evaluator.evaluate("evil")).matched is True
        assert (await evaluator.evaluate("good")).matched is False

    @pytest.mark.asyncio
    async def test_any_no_match(self):
        """Test list evaluator as allowlist (any/no_match)."""
        # Given: A list evaluator as allowlist
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["safe", "ok"], "logic": "any", "match_on": "no_match"},
        )
        evaluator = get_evaluator(config)

        # When/Then: Allowlist items don't match, others do
        assert (await evaluator.evaluate("safe")).matched is False
        assert (await evaluator.evaluate("ok")).matched is False
        assert (await evaluator.evaluate("dangerous")).matched is True

    @pytest.mark.asyncio
    async def test_all_match(self):
        """Test list evaluator with all/match logic."""
        # Given: A list evaluator with all/match logic
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["valid1", "valid2"], "logic": "all", "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        # When/Then: Matches only when all values present
        assert (await evaluator.evaluate(["valid1", "valid2"])).matched is True
        assert (await evaluator.evaluate(["valid1", "invalid"])).matched is False
        assert (await evaluator.evaluate([])).matched is False

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        """Test case-insensitive matching."""
        # Given: A case-insensitive list evaluator
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["MixedCase"], "case_sensitive": False, "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        # When/Then: Matches regardless of case
        assert (await evaluator.evaluate("mixedcase")).matched is True
        assert (await evaluator.evaluate("MIXEDCASE")).matched is True


class TestGetEvaluator:
    """Tests for the get_evaluator factory function."""

    def test_get_evaluator_returns_plugin_instance(self):
        """Test factory returns correct plugin type."""
        # Given: An evaluator config
        config = EvaluatorConfig(plugin="regex", config={"pattern": "abc"})
        # When: Getting evaluator
        evaluator = get_evaluator(config)

        # Then: Returns correct plugin type
        assert isinstance(evaluator, RegexControlEvaluatorPlugin)
        assert evaluator.config.pattern == "abc"

    def test_get_evaluator_unknown_plugin(self):
        """Test error when plugin not found."""
        # Given: Config for nonexistent plugin
        config = EvaluatorConfig(plugin="nonexistent", config={})

        # When/Then: Should raise ValueError
        with pytest.raises(ValueError, match="not found"):
            get_evaluator(config)

    def test_get_available_plugins(self):
        """Test listing available plugins."""
        # Given/When: Getting available plugins
        plugins = get_available_plugins()

        # Then: Should include built-in plugins
        assert "regex" in plugins
        assert "list" in plugins


class TestEvaluatorCache:
    """Tests for evaluator instance caching."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_evaluator_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        clear_evaluator_cache()

    def test_evaluator_cache_hit(self):
        """Test that same config returns same cached instance."""
        # Given: An evaluator config
        config = EvaluatorConfig(plugin="regex", config={"pattern": "test"})

        # When: First call creates instance
        evaluator1 = get_evaluator(config)
        # When: Second call with same config
        evaluator2 = get_evaluator(config)

        # Then: Should return same cached instance
        assert evaluator1 is evaluator2, "Same config should return cached instance"

    def test_evaluator_cache_miss_different_config(self):
        """Test that different configs return different instances."""
        # Given: Two different configs
        config1 = EvaluatorConfig(plugin="regex", config={"pattern": "test1"})
        config2 = EvaluatorConfig(plugin="regex", config={"pattern": "test2"})

        # When: Getting evaluators
        evaluator1 = get_evaluator(config1)
        evaluator2 = get_evaluator(config2)

        # Then: Should return different instances
        assert evaluator1 is not evaluator2, "Different configs should return different instances"

    def test_evaluator_cache_miss_different_plugin(self):
        """Test that same config but different plugins return different instances."""
        # Given: Two configs with different plugins
        config1 = EvaluatorConfig(plugin="regex", config={"pattern": "bad"})
        config2 = EvaluatorConfig(plugin="list", config={"values": ["bad"]})

        # When: Getting evaluators
        evaluator1 = get_evaluator(config1)
        evaluator2 = get_evaluator(config2)

        # Then: Should return different plugin types
        assert evaluator1 is not evaluator2
        assert isinstance(evaluator1, RegexControlEvaluatorPlugin)
        assert isinstance(evaluator2, ListControlEvaluatorPlugin)

    def test_evaluator_cache_clear_all(self):
        """Test that clear_evaluator_cache clears all entries."""
        # Given: Two cached evaluators
        config1 = EvaluatorConfig(plugin="regex", config={"pattern": "test1"})
        config2 = EvaluatorConfig(plugin="list", config={"values": ["test"]})
        evaluator1a = get_evaluator(config1)
        evaluator2a = get_evaluator(config2)

        # When: Clearing cache
        clear_evaluator_cache()

        # When: Getting instances again
        evaluator1b = get_evaluator(config1)
        evaluator2b = get_evaluator(config2)

        # Then: Both should be new instances
        assert evaluator1a is not evaluator1b, "Should be new instance after clear"
        assert evaluator2a is not evaluator2b, "Should be new instance after clear"


class TestCacheSizeClamping:
    """Tests for EVALUATOR_CACHE_SIZE clamping behavior."""

    def test_cache_size_is_clamped_to_minimum(self):
        """Verify cache size is clamped to at least 1.

        Given: EVALUATOR_CACHE_SIZE constant exists
        When: Module is imported
        Then: The value should be at least 1 (MIN_CACHE_SIZE)
        """
        from agent_control_engine.evaluators import EVALUATOR_CACHE_SIZE, MIN_CACHE_SIZE

        assert EVALUATOR_CACHE_SIZE >= MIN_CACHE_SIZE
        assert MIN_CACHE_SIZE == 1
