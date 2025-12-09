"""Tests for unified evaluator factory."""

import pytest
from agent_control_models import (
    EvaluatorConfig,
    RegexConfig,
    ListConfig,
    get_plugin,
    clear_plugins,
)
from agent_control_plugins import RegexPlugin, ListPlugin

from agent_control_engine.evaluators import (
    get_evaluator,
    get_available_plugins,
    clear_evaluator_cache,
    invalidate_evaluator_cache,
)


class TestRegexPlugin:
    """Tests for the regex plugin via the evaluator factory."""

    @pytest.mark.asyncio
    async def test_basic_match(self):
        """Test regex matches SSN pattern."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        evaluator = get_evaluator(config)

        result = await evaluator.evaluate("My SSN is 123-45-6789")

        assert result.matched is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_no_match(self):
        """Test regex doesn't match when pattern not found."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        evaluator = get_evaluator(config)

        result = await evaluator.evaluate("No numbers here")

        assert result.matched is False
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_non_string_input(self):
        """Test non-string input is converted to string."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"123"})
        evaluator = get_evaluator(config)

        result = await evaluator.evaluate(12345)

        assert result.matched is True

    @pytest.mark.asyncio
    async def test_none_input(self):
        """Test handling of None input."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r".*"})
        evaluator = get_evaluator(config)

        result = await evaluator.evaluate(None)

        assert result.matched is False
        assert result.message == "No data to match"

    def test_invalid_regex_pattern(self):
        """Test invalid regex pattern raises error."""
        with pytest.raises(ValueError):
            RegexConfig(pattern="[")

    @pytest.mark.asyncio
    async def test_empty_pattern_matches_everything(self):
        """Test empty pattern matches everything."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": ""})
        evaluator = get_evaluator(config)

        result = await evaluator.evaluate("something")

        assert result.matched is True


class TestListPlugin:
    """Tests for the list plugin via the evaluator factory."""

    @pytest.mark.asyncio
    async def test_any_match(self):
        """Test list evaluator with any/match logic."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["bad", "evil"], "logic": "any", "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        assert (await evaluator.evaluate("bad")).matched is True
        assert (await evaluator.evaluate("evil")).matched is True
        assert (await evaluator.evaluate("good")).matched is False

    @pytest.mark.asyncio
    async def test_any_no_match(self):
        """Test list evaluator as allowlist (any/no_match)."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["safe", "ok"], "logic": "any", "match_on": "no_match"},
        )
        evaluator = get_evaluator(config)

        assert (await evaluator.evaluate("safe")).matched is False
        assert (await evaluator.evaluate("ok")).matched is False
        assert (await evaluator.evaluate("dangerous")).matched is True

    @pytest.mark.asyncio
    async def test_all_match(self):
        """Test list evaluator with all/match logic."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["valid1", "valid2"], "logic": "all", "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        assert (await evaluator.evaluate(["valid1", "valid2"])).matched is True
        assert (await evaluator.evaluate(["valid1", "invalid"])).matched is False
        assert (await evaluator.evaluate([])).matched is False

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        """Test case-insensitive matching."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["MixedCase"], "case_sensitive": False, "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        assert (await evaluator.evaluate("mixedcase")).matched is True
        assert (await evaluator.evaluate("MIXEDCASE")).matched is True


class TestGetEvaluator:
    """Tests for the get_evaluator factory function."""

    def test_get_evaluator_returns_plugin_instance(self):
        """Test factory returns correct plugin type."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": "abc"})
        evaluator = get_evaluator(config)

        assert isinstance(evaluator, RegexPlugin)
        assert evaluator.config.pattern == "abc"

    def test_get_evaluator_unknown_plugin(self):
        """Test error when plugin not found."""
        config = EvaluatorConfig(plugin="nonexistent", config={})

        with pytest.raises(ValueError, match="not found"):
            get_evaluator(config)

    def test_get_available_plugins(self):
        """Test listing available plugins."""
        plugins = get_available_plugins()

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
        config = EvaluatorConfig(plugin="regex", config={"pattern": "test"})

        # First call creates instance
        evaluator1 = get_evaluator(config)
        # Second call with same config should return same instance
        evaluator2 = get_evaluator(config)

        assert evaluator1 is evaluator2, "Same config should return cached instance"

    def test_evaluator_cache_miss_different_config(self):
        """Test that different configs return different instances."""
        config1 = EvaluatorConfig(plugin="regex", config={"pattern": "test1"})
        config2 = EvaluatorConfig(plugin="regex", config={"pattern": "test2"})

        evaluator1 = get_evaluator(config1)
        evaluator2 = get_evaluator(config2)

        assert evaluator1 is not evaluator2, "Different configs should return different instances"

    def test_evaluator_cache_miss_different_plugin(self):
        """Test that same config but different plugins return different instances."""
        config1 = EvaluatorConfig(plugin="regex", config={"pattern": "bad"})
        config2 = EvaluatorConfig(plugin="list", config={"values": ["bad"]})

        evaluator1 = get_evaluator(config1)
        evaluator2 = get_evaluator(config2)

        assert evaluator1 is not evaluator2
        assert isinstance(evaluator1, RegexPlugin)
        assert isinstance(evaluator2, ListPlugin)

    def test_evaluator_cache_invalidation_by_plugin(self):
        """Test that invalidate_evaluator_cache clears entries for specific plugin."""
        config_regex = EvaluatorConfig(plugin="regex", config={"pattern": "test"})
        config_list = EvaluatorConfig(plugin="list", config={"values": ["test"]})

        # Create cached instances
        evaluator_regex1 = get_evaluator(config_regex)
        evaluator_list1 = get_evaluator(config_list)

        # Invalidate only regex
        invalidate_evaluator_cache("regex")

        # Get instances again
        evaluator_regex2 = get_evaluator(config_regex)
        evaluator_list2 = get_evaluator(config_list)

        # Regex should be new instance, list should be same
        assert evaluator_regex1 is not evaluator_regex2, "Regex should be new instance after invalidation"
        assert evaluator_list1 is evaluator_list2, "List should still be cached"

    def test_evaluator_cache_clear_all(self):
        """Test that clear_evaluator_cache clears all entries."""
        config1 = EvaluatorConfig(plugin="regex", config={"pattern": "test1"})
        config2 = EvaluatorConfig(plugin="list", config={"values": ["test"]})

        # Create cached instances
        evaluator1a = get_evaluator(config1)
        evaluator2a = get_evaluator(config2)

        # Clear all
        clear_evaluator_cache()

        # Get instances again
        evaluator1b = get_evaluator(config1)
        evaluator2b = get_evaluator(config2)

        # Both should be new instances
        assert evaluator1a is not evaluator1b, "Should be new instance after clear"
        assert evaluator2a is not evaluator2b, "Should be new instance after clear"
