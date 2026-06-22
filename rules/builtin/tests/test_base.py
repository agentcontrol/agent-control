"""Tests for rule base classes.

Architecture: Rules take config at __init__, evaluate() only takes data.
"""

import pytest
from typing import Any

from agent_control_rules import Rule, RuleConfig, RuleMetadata
from agent_control_models import RuleResult


class MockConfig(RuleConfig):
    """Config model for mock rule."""

    should_match: bool = False
    timeout_ms: int = 5000


class MockRule(Rule[MockConfig]):
    """A mock rule for testing."""

    metadata = RuleMetadata(
        name="mock-rule",
        version="1.0.0",
        description="A mock rule for testing",
        requires_api_key=False,
        timeout_ms=5000,
    )
    config_model = MockConfig

    async def evaluate(self, data: Any) -> RuleResult:
        """Simple mock evaluation."""
        return RuleResult(
            matched=self.config.should_match,
            confidence=1.0,
            message="Mock evaluation",
            metadata={"data": str(data)},
        )


class TestRuleMetadata:
    """Tests for RuleMetadata dataclass."""

    def test_metadata_with_defaults(self):
        """Test metadata with default values."""
        metadata = RuleMetadata(
            name="test-rule",
            version="1.0.0",
            description="Test rule",
        )

        assert metadata.name == "test-rule"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test rule"
        assert metadata.requires_api_key is False
        assert metadata.timeout_ms == 10000

    def test_metadata_with_all_fields(self):
        """Test metadata with all fields specified."""
        metadata = RuleMetadata(
            name="full-rule",
            version="2.0.0",
            description="Full rule",
            requires_api_key=True,
            timeout_ms=15000,
        )

        assert metadata.name == "full-rule"
        assert metadata.version == "2.0.0"
        assert metadata.requires_api_key is True
        assert metadata.timeout_ms == 15000


class TestRule:
    """Tests for Rule base class."""

    def test_rule_is_abstract(self):
        """Test that Rule is an ABC."""
        from abc import ABC
        assert issubclass(Rule, ABC)

    def test_mock_rule_metadata(self):
        """Test that mock rule has correct metadata."""
        assert MockRule.metadata.name == "mock-rule"
        assert MockRule.metadata.version == "1.0.0"
        assert MockRule.metadata.timeout_ms == 5000

    @pytest.mark.asyncio
    async def test_mock_rule_evaluate(self):
        """Test mock rule evaluation."""
        rule = MockRule.from_dict({"should_match": True})

        result = await rule.evaluate("test data")

        assert result.matched is True
        assert result.confidence == 1.0
        assert result.metadata["data"] == "test data"

    @pytest.mark.asyncio
    async def test_mock_rule_evaluate_no_match(self):
        """Test mock rule evaluation without match."""
        rule = MockRule.from_dict({"should_match": False})

        result = await rule.evaluate("test data")

        assert result.matched is False

    def test_rule_config_stored(self):
        """Test that rule stores config."""
        rule = MockRule.from_dict({"should_match": True})

        assert isinstance(rule.config, MockConfig)
        assert rule.config.should_match is True

    def test_get_timeout_seconds_from_config(self):
        """Test timeout conversion from config."""
        rule = MockRule.from_dict({"timeout_ms": 3000})

        assert rule.get_timeout_seconds() == 3.0

    def test_get_timeout_seconds_different_values(self):
        """Test timeout with different values."""
        rule1 = MockRule.from_dict({"timeout_ms": 7500})
        rule2 = MockRule.from_dict({"timeout_ms": 1000})

        assert rule1.get_timeout_seconds() == 7.5
        assert rule2.get_timeout_seconds() == 1.0

    def test_get_timeout_seconds_from_default(self):
        """Test timeout uses metadata default when not in config."""
        rule = MockRule.from_dict({})  # No timeout_ms in config

        # MockConfig has default timeout_ms=5000
        assert rule.get_timeout_seconds() == 5.0

    def test_cannot_instantiate_abstract_class(self):
        """Test that Rule cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            Rule({})  # type: ignore
