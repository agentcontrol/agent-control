"""Tests for rule system integration with the unified architecture.

These tests verify the rule system works correctly with the engine.
"""

from typing import Any

# Import to ensure built-in rules are registered
import agent_control_rules  # noqa: F401
import pytest
from agent_control_engine import get_rule_instance
from agent_control_rules import Rule, RuleMetadata, register_rule
from agent_control_models import RuleResult, RuleSpec
from pydantic import BaseModel


class MockConfig(BaseModel):
    """Config for mock rule."""

    threshold: float = 0.5


class MockTestRule(Rule[MockConfig]):
    """Mock rule for engine testing."""

    metadata = RuleMetadata(
        name="test-mock-rule",
        version="1.0.0",
        description="Test rule for engine tests",
    )
    config_model = MockConfig

    async def evaluate(self, data: Any) -> RuleResult:
        """Mock evaluation."""
        value = float(data) if isinstance(data, (int, float)) else 0.0
        matched = value > self.config.threshold

        return RuleResult(
            matched=matched,
            confidence=1.0,
            message=f"Value {value} vs threshold {self.config.threshold}",
            metadata={"value": value, "threshold": self.config.threshold},
        )


class TestRuleArchitecture:
    """Tests verifying the rule architecture."""

    def test_rule_is_abc_subclass(self):
        """Test Rule is an ABC."""
        # Given/When: Checking Rule base class
        from abc import ABC

        # Then: Should be subclass of ABC
        assert issubclass(Rule, ABC)

    def test_rule_has_required_attributes(self):
        """Test rules have required class attributes."""
        # Given/When: Checking MockTestRule
        # Then: Should have required attributes
        assert hasattr(MockTestRule, "metadata")
        assert hasattr(MockTestRule, "config_model")
        assert MockTestRule.metadata.name == "test-mock-rule"

    def test_rule_from_dict(self):
        """Test creating rule from dict config."""
        # Given/When: Creating rule from dict
        rule = MockTestRule.from_dict({"threshold": 0.7})

        # Then: Config should be parsed correctly
        assert isinstance(rule.config, MockConfig)
        assert rule.config.threshold == 0.7


class TestMockRuleEvaluation:
    """Tests for mock rule evaluation."""

    @pytest.fixture(autouse=True)
    def register_mock(self):
        """Register mock rule for tests."""
        register_rule(MockTestRule)
        yield
        # Don't clear - other tests need built-in rules

    @pytest.mark.asyncio
    async def test_evaluate_matched(self):
        """Test evaluation when threshold exceeded."""
        # Given: Mock rule with threshold 0.5
        config = RuleSpec(name="test-mock-rule", config={"threshold": 0.5})
        rule = get_rule_instance(config)

        # When: Evaluating value above threshold
        result = await rule.evaluate(0.8)

        # Then: Should match with metadata
        assert result.matched is True
        assert result.confidence == 1.0
        assert result.metadata["value"] == 0.8
        assert result.metadata["threshold"] == 0.5

    @pytest.mark.asyncio
    async def test_evaluate_not_matched(self):
        """Test evaluation when below threshold."""
        # Given: Mock rule with threshold 0.9
        config = RuleSpec(name="test-mock-rule", config={"threshold": 0.9})
        rule = get_rule_instance(config)

        # When: Evaluating value below threshold
        result = await rule.evaluate(0.3)

        # Then: Should not match
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_multiple_evaluations(self):
        """Test multiple evaluations with same rule."""
        # Given: Mock rule with threshold 0.5
        config = RuleSpec(name="test-mock-rule", config={"threshold": 0.5})
        rule = get_rule_instance(config)

        # When: Evaluating multiple values
        results = [
            await rule.evaluate(0.2),
            await rule.evaluate(0.6),
            await rule.evaluate(0.9),
        ]

        # Then: Results depend on threshold comparison
        assert results[0].matched is False  # 0.2 < 0.5
        assert results[1].matched is True  # 0.6 > 0.5
        assert results[2].matched is True  # 0.9 > 0.5


class TestRuleMetadata:
    """Tests for rule metadata."""

    def test_access_metadata(self):
        """Test that rule metadata is accessible."""
        # Given/When: Accessing MockTestRule metadata
        # Then: All fields should be correct
        assert MockTestRule.metadata.name == "test-mock-rule"
        assert MockTestRule.metadata.version == "1.0.0"
        assert MockTestRule.metadata.description == "Test rule for engine tests"

    def test_config_schema(self):
        """Test that config model provides JSON schema."""
        # Given/When: Getting JSON schema from config model
        schema = MockTestRule.config_model.model_json_schema()

        # Then: Schema should include threshold property
        assert "properties" in schema
        assert "threshold" in schema["properties"]


class TestBuiltInRules:
    """Tests for built-in rules."""

    def test_regex_rule_registered(self):
        """Test regex rule is registered."""
        # Given/When: Getting regex rule
        from agent_control_engine import list_rules
        rule = list_rules().get("regex")

        # Then: Should be registered with correct name
        assert rule is not None
        assert rule.metadata.name == "regex"

    def test_list_rule_registered(self):
        """Test list rule is registered."""
        # Given/When: Getting list rule
        from agent_control_engine import list_rules
        rule = list_rules().get("list")

        # Then: Should be registered with correct name
        assert rule is not None
        assert rule.metadata.name == "list"


class TestRegexRuleFlags:
    """Tests for regex rule flag handling."""

    @pytest.mark.asyncio
    async def test_regex_case_sensitive_by_default(self):
        """Test regex is case-sensitive by default.

        Given: A regex pattern without flags
        When: Evaluating against different case text
        Then: Only exact case matches
        """
        # Given: Regex for "SECRET" without flags
        config = RuleSpec(
            name="regex",
            config={"pattern": "SECRET"}
        )
        rule = get_rule_instance(config)

        # When/Then: Exact case matches
        result = await rule.evaluate("the SECRET is here")
        assert result.matched is True

        # When/Then: Different case does NOT match
        result = await rule.evaluate("the secret is here")
        assert result.matched is False

        result = await rule.evaluate("the Secret is here")
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_regex_ignorecase_flag(self):
        """Test regex IGNORECASE flag works.

        Given: A regex pattern with IGNORECASE flag
        When: Evaluating against different case text
        Then: All cases match
        """
        # Given: Regex for "SECRET" with IGNORECASE flag
        config = RuleSpec(
            name="regex",
            config={"pattern": "SECRET", "flags": ["IGNORECASE"]}
        )
        rule = get_rule_instance(config)

        # When/Then: All case variations should match
        result = await rule.evaluate("the SECRET is here")
        assert result.matched is True

        result = await rule.evaluate("the secret is here")
        assert result.matched is True

        result = await rule.evaluate("the Secret is here")
        assert result.matched is True

        result = await rule.evaluate("the sEcReT is here")
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_regex_short_i_flag(self):
        """Test regex short 'I' flag works.

        Given: A regex pattern with 'I' flag (short for IGNORECASE)
        When: Evaluating against different case text
        Then: All cases match
        """
        # Given: Regex with short "I" flag
        config = RuleSpec(
            name="regex",
            config={"pattern": "password", "flags": ["I"]}
        )
        rule = get_rule_instance(config)

        # When/Then: All case variations should match
        result = await rule.evaluate("PASSWORD")
        assert result.matched is True

        result = await rule.evaluate("password")
        assert result.matched is True

        result = await rule.evaluate("Password")
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_regex_ignorecase_lowercase_flag(self):
        """Test regex ignorecase flag works with lowercase.

        Given: A regex pattern with lowercase 'ignorecase' flag
        When: Evaluating against different case text
        Then: All cases match
        """
        # Given: Regex with lowercase flag variant
        config = RuleSpec(
            name="regex",
            config={"pattern": "admin", "flags": ["ignorecase"]}
        )
        rule = get_rule_instance(config)

        # When/Then: Should work with lowercase flag
        result = await rule.evaluate("ADMIN")
        assert result.matched is True

        result = await rule.evaluate("admin")
        assert result.matched is True
