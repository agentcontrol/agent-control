"""Tests for unified rule factory."""

import pytest
from agent_control_engine import (
    clear_rule_cache,
    get_rule_instance,
    list_rules,
)
from agent_control_models import RuleSpec
from agent_control_rules import (
    ListRule,
    RegexRule,
    RegexRuleConfig,
)


class TestRegexRule:
    """Tests for the regex rule via the rule factory."""

    @pytest.mark.asyncio
    async def test_basic_match(self):
        """Test regex matches SSN pattern."""
        # Given: A regex rule with SSN pattern
        config = RuleSpec(name="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        rule = get_rule_instance(config)

        # When: Evaluating text containing SSN
        result = await rule.evaluate("My SSN is 123-45-6789")

        # Then: Should match with high confidence
        assert result.matched is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_no_match(self):
        """Test regex doesn't match when pattern not found."""
        # Given: A regex rule with SSN pattern
        config = RuleSpec(name="regex", config={"pattern": r"\d{3}-\d{2}-\d{4}"})
        rule = get_rule_instance(config)

        # When: Evaluating text without pattern
        result = await rule.evaluate("No numbers here")

        # Then: Should not match
        assert result.matched is False
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_non_string_input(self):
        """Test non-string input is converted to string."""
        # Given: A regex rule
        config = RuleSpec(name="regex", config={"pattern": r"123"})
        rule = get_rule_instance(config)

        # When: Evaluating non-string input
        result = await rule.evaluate(12345)

        # Then: Should match after conversion
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_none_input(self):
        """Test handling of None input."""
        # Given: A regex rule
        config = RuleSpec(name="regex", config={"pattern": r".*"})
        rule = get_rule_instance(config)

        # When: Evaluating None
        result = await rule.evaluate(None)

        # Then: Should not match and return message
        assert result.matched is False
        assert result.message == "No data to match"

    def test_invalid_regex_pattern(self):
        """Test invalid regex pattern raises error."""
        # Given/When: Creating config with invalid pattern
        # Then: Should raise ValueError
        with pytest.raises(ValueError):
            RegexRuleConfig(pattern="[")

    @pytest.mark.asyncio
    async def test_empty_pattern_matches_everything(self):
        """Test empty pattern matches everything."""
        # Given: A regex rule with empty pattern
        config = RuleSpec(name="regex", config={"pattern": ""})
        rule = get_rule_instance(config)

        # When: Evaluating any text
        result = await rule.evaluate("something")

        # Then: Should match
        assert result.matched is True


class TestListRule:
    """Tests for the list rule via the rule factory."""

    @pytest.mark.asyncio
    async def test_any_match(self):
        """Test list rule with any/match logic."""
        # Given: A list rule with blocklist items
        config = RuleSpec(
            name="list",
            config={"values": ["bad", "evil"], "logic": "any", "match_on": "match"},
        )
        rule = get_rule_instance(config)

        # When/Then: Blocklist items match, others don't
        assert (await rule.evaluate("bad")).matched is True
        assert (await rule.evaluate("evil")).matched is True
        assert (await rule.evaluate("good")).matched is False

    @pytest.mark.asyncio
    async def test_any_no_match(self):
        """Test list rule as allowlist (any/no_match)."""
        # Given: A list rule as allowlist
        config = RuleSpec(
            name="list",
            config={"values": ["safe", "ok"], "logic": "any", "match_on": "no_match"},
        )
        rule = get_rule_instance(config)

        # When/Then: Allowlist items don't match, others do
        assert (await rule.evaluate("safe")).matched is False
        assert (await rule.evaluate("ok")).matched is False
        assert (await rule.evaluate("dangerous")).matched is True

    @pytest.mark.asyncio
    async def test_all_match(self):
        """Test list rule with all/match logic."""
        # Given: A list rule with all/match logic
        config = RuleSpec(
            name="list",
            config={"values": ["valid1", "valid2"], "logic": "all", "match_on": "match"},
        )
        rule = get_rule_instance(config)

        # When/Then: Matches only when all values present
        assert (await rule.evaluate(["valid1", "valid2"])).matched is True
        assert (await rule.evaluate(["valid1", "invalid"])).matched is False
        assert (await rule.evaluate([])).matched is False

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        """Test case-insensitive matching."""
        # Given: A case-insensitive list rule
        config = RuleSpec(
            name="list",
            config={"values": ["MixedCase"], "case_sensitive": False, "match_on": "match"},
        )
        rule = get_rule_instance(config)

        # When/Then: Matches regardless of case
        assert (await rule.evaluate("mixedcase")).matched is True
        assert (await rule.evaluate("MIXEDCASE")).matched is True


class TestGetRuleInstance:
    """Tests for the get_rule_instance factory function."""

    def test_get_rule_instance_returns_correct_type(self):
        """Test factory returns correct rule type."""
        # Given: A rule config
        config = RuleSpec(name="regex", config={"pattern": "abc"})
        # When: Getting rule
        rule = get_rule_instance(config)

        # Then: Returns correct rule type
        assert isinstance(rule, RegexRule)
        assert rule.config.pattern == "abc"

    def test_get_rule_instance_unknown_rule(self):
        """Test error when rule not found."""
        # Given: Config for nonexistent rule
        config = RuleSpec(name="nonexistent", config={})

        # When/Then: Should raise ValueError
        with pytest.raises(ValueError, match="not found"):
            get_rule_instance(config)

    def test_list_rules(self):
        """Test listing available rules."""
        # Given/When: Getting available rules
        rules = list_rules()

        # Then: Should include built-in rules
        assert "regex" in rules
        assert "list" in rules


class TestRuleCache:
    """Tests for rule instance caching."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_rule_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        clear_rule_cache()

    def test_rule_cache_hit(self):
        """Test that same config returns same cached instance."""
        # Given: A rule config
        config = RuleSpec(name="regex", config={"pattern": "test"})

        # When: First call creates instance
        rule1 = get_rule_instance(config)
        # When: Second call with same config
        rule2 = get_rule_instance(config)

        # Then: Should return same cached instance
        assert rule1 is rule2, "Same config should return cached instance"

    def test_rule_cache_miss_different_config(self):
        """Test that different configs return different instances."""
        # Given: Two different configs
        config1 = RuleSpec(name="regex", config={"pattern": "test1"})
        config2 = RuleSpec(name="regex", config={"pattern": "test2"})

        # When: Getting rules
        rule1 = get_rule_instance(config1)
        rule2 = get_rule_instance(config2)

        # Then: Should return different instances
        assert rule1 is not rule2, "Different configs should return different instances"

    def test_rule_cache_miss_different_rule(self):
        """Test that same config but different rules return different instances."""
        # Given: Two configs with different rules
        config1 = RuleSpec(name="regex", config={"pattern": "bad"})
        config2 = RuleSpec(name="list", config={"values": ["bad"]})

        # When: Getting rules
        rule1 = get_rule_instance(config1)
        rule2 = get_rule_instance(config2)

        # Then: Should return different rule types
        assert rule1 is not rule2
        assert isinstance(rule1, RegexRule)
        assert isinstance(rule2, ListRule)

    def test_rule_cache_clear_all(self):
        """Test that clear_rule_cache clears all entries."""
        # Given: Two cached rules
        config1 = RuleSpec(name="regex", config={"pattern": "test1"})
        config2 = RuleSpec(name="list", config={"values": ["test"]})
        rule1a = get_rule_instance(config1)
        rule2a = get_rule_instance(config2)

        # When: Clearing cache
        clear_rule_cache()

        # When: Getting instances again
        rule1b = get_rule_instance(config1)
        rule2b = get_rule_instance(config2)

        # Then: Both should be new instances
        assert rule1a is not rule1b, "Should be new instance after clear"
        assert rule2a is not rule2b, "Should be new instance after clear"


class TestCacheSizeClamping:
    """Tests for RULE_CACHE_SIZE clamping behavior."""

    def test_cache_size_is_clamped_to_minimum(self):
        """Verify cache size is clamped to at least 1.

        Given: RULE_CACHE_SIZE constant exists
        When: Module is imported
        Then: The value should be at least 1 (MIN_CACHE_SIZE)
        """
        from agent_control_rules._factory import RULE_CACHE_SIZE, MIN_CACHE_SIZE

        assert RULE_CACHE_SIZE >= MIN_CACHE_SIZE
        assert MIN_CACHE_SIZE == 1
