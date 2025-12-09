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

from agent_control_engine.evaluators import get_evaluator, get_available_plugins


class TestRegexPlugin:
    """Tests for the regex plugin via the evaluator factory."""

    def test_basic_match(self):
        """Test regex matches SSN pattern."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        evaluator = get_evaluator(config)

        result = evaluator.evaluate("My SSN is 123-45-6789")

        assert result.matched is True
        assert result.confidence == 1.0

    def test_no_match(self):
        """Test regex doesn't match when pattern not found."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        evaluator = get_evaluator(config)

        result = evaluator.evaluate("No numbers here")

        assert result.matched is False
        assert result.confidence == 1.0

    def test_non_string_input(self):
        """Test non-string input is converted to string."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r"123"})
        evaluator = get_evaluator(config)

        result = evaluator.evaluate(12345)

        assert result.matched is True

    def test_none_input(self):
        """Test handling of None input."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": r".*"})
        evaluator = get_evaluator(config)

        result = evaluator.evaluate(None)

        assert result.matched is False
        assert result.message == "No data to match"

    def test_invalid_regex_pattern(self):
        """Test invalid regex pattern raises error."""
        with pytest.raises(ValueError):
            RegexConfig(pattern="[")

    def test_empty_pattern_matches_everything(self):
        """Test empty pattern matches everything."""
        config = EvaluatorConfig(plugin="regex", config={"pattern": ""})
        evaluator = get_evaluator(config)

        result = evaluator.evaluate("something")

        assert result.matched is True


class TestListPlugin:
    """Tests for the list plugin via the evaluator factory."""

    def test_any_match(self):
        """Test list evaluator with any/match logic."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["bad", "evil"], "logic": "any", "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        assert evaluator.evaluate("bad").matched is True
        assert evaluator.evaluate("evil").matched is True
        assert evaluator.evaluate("good").matched is False

    def test_any_no_match(self):
        """Test list evaluator as allowlist (any/no_match)."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["safe", "ok"], "logic": "any", "match_on": "no_match"},
        )
        evaluator = get_evaluator(config)

        assert evaluator.evaluate("safe").matched is False
        assert evaluator.evaluate("ok").matched is False
        assert evaluator.evaluate("dangerous").matched is True

    def test_all_match(self):
        """Test list evaluator with all/match logic."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["valid1", "valid2"], "logic": "all", "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        assert evaluator.evaluate(["valid1", "valid2"]).matched is True
        assert evaluator.evaluate(["valid1", "invalid"]).matched is False
        assert evaluator.evaluate([]).matched is False

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        config = EvaluatorConfig(
            plugin="list",
            config={"values": ["MixedCase"], "case_sensitive": False, "match_on": "match"},
        )
        evaluator = get_evaluator(config)

        assert evaluator.evaluate("mixedcase").matched is True
        assert evaluator.evaluate("MIXEDCASE").matched is True


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
        assert "custom-code" in plugins
