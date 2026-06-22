"""Unit tests for the rule system.

Tests rule registration, discovery, and base functionality without
requiring actual rule implementations or external services.

Rules take config at __init__, evaluate() only takes data.
Registry, base classes, and discovery are in agent_control_rules.
"""

import pytest
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from agent_control.rules import (
    Rule,
    RuleMetadata,
    discover_rules,
    list_rules,
    register_rule,
)
from agent_control_rules import clear_rules
from agent_control_engine import reset_rule_discovery
from agent_control_models.controls import RuleResult


class MockConfig(BaseModel):
    """Config model for MockRule."""
    threshold: float = 0.5


class MockRule(Rule):
    """Mock rule for testing.

    Config is passed at __init__, not at evaluate().
    """

    metadata = RuleMetadata(
        name="test-mock-rule",
        version="1.0.0",
        description="Mock rule for testing",
        requires_api_key=False,
        timeout_ms=10,
    )
    config_model = MockConfig

    def __init__(self, config: dict):
        super().__init__(config)
        self.threshold = config.get("threshold", 0.5)

    def evaluate(self, data) -> RuleResult:
        """Mock evaluation (synchronous)."""
        matched = float(data) > self.threshold if isinstance(data, (int, float)) else False
        return RuleResult(
            matched=matched,
            confidence=1.0,
            message=f"Mock evaluation: {matched}",
            metadata={"threshold": self.threshold},
        )


class TestRuleMetadata:
    """Tests for RuleMetadata dataclass."""

    def test_metadata_creation(self):
        """Test creating rule metadata."""
        metadata = RuleMetadata(
            name="test-rule",
            version="1.0.0",
            description="Test rule",
        )

        assert metadata.name == "test-rule"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test rule"
        assert metadata.requires_api_key is False
        assert metadata.timeout_ms == 10000  # Default

    def test_metadata_with_all_fields(self):
        """Test metadata with all fields populated."""
        metadata = RuleMetadata(
            name="full-rule",
            version="2.0.0",
            description="Full test",
            requires_api_key=True,
            timeout_ms=5000,
        )

        assert metadata.requires_api_key is True
        assert metadata.timeout_ms == 5000


class TestRuleRegistry:
    """Tests for rule registry functionality."""

    def setup_method(self):
        """Clear registry before each test."""
        # Clear all rules and reset discovery
        clear_rules()
        reset_rule_discovery()
        # Run discovery to load built-in rules
        discover_rules()

    def test_register_rule(self):
        """Test registering a rule."""
        # Register mock rule
        register_rule(MockRule)

        # Verify it's registered
        rule_class = list_rules().get("test-mock-rule")
        assert rule_class is MockRule

    def test_get_nonexistent_rule(self):
        """Test getting a rule that doesn't exist."""
        rule_class = list_rules().get("nonexistent-rule-xyz")
        assert rule_class is None

    def test_list_rules_includes_registered(self):
        """Test listing rules includes registered rules."""
        # Register mock rule
        register_rule(MockRule)

        # List rules - now returns dict of rule classes
        rules = list_rules()

        assert "test-mock-rule" in rules
        assert rules["test-mock-rule"] is MockRule

    def test_builtin_rules_available(self):
        """Test that built-in rules are available after discovery."""
        rules = list_rules()

        assert "regex" in rules
        assert "list" in rules

    def test_register_duplicate_rule_raises_error(self):
        """Test that registering a different rule with same name raises ValueError."""
        # Register rule first
        register_rule(MockRule)

        # Create a different class with the same rule name
        class DuplicateRule(Rule):
            metadata = RuleMetadata(
                name="test-mock-rule",  # Same name as MockRule
                version="2.0.0",
                description="Duplicate rule",
            )
            config_model = MockConfig

            def evaluate(self, data) -> RuleResult:
                return RuleResult(matched=False, confidence=1.0, message="duplicate")

        # Second registration with different class should fail
        with pytest.raises(ValueError, match="already registered"):
            register_rule(DuplicateRule)

    def test_re_register_same_rule_allowed(self):
        """Test that re-registering the same class is allowed (hot reload support)."""
        register_rule(MockRule)
        # Should not raise - same class can be re-registered
        result = register_rule(MockRule)
        assert result is MockRule


class TestRuleBase:
    """Tests for Rule base class."""

    def test_rule_evaluate(self):
        """Test synchronous evaluation."""
        # Config is now passed at init
        rule = MockRule({"threshold": 0.5})
        result = rule.evaluate(data=0.8)

        assert isinstance(result, RuleResult)
        assert result.matched is True
        assert result.confidence == 1.0
        assert "Mock evaluation" in result.message

    def test_rule_evaluate_no_match(self):
        """Test evaluation when rule doesn't match."""
        rule = MockRule({"threshold": 0.5})
        result = rule.evaluate(data=0.3)

        assert isinstance(result, RuleResult)
        assert result.matched is False
        assert result.confidence == 1.0

    def test_rule_with_different_configs(self):
        """Test rule uses config correctly (set at init)."""
        # Create two rules with different configs
        rule_low = MockRule({"threshold": 0.5})
        rule_high = MockRule({"threshold": 0.7})

        # Same data, different thresholds
        assert rule_low.evaluate(data=0.6).matched is True
        assert rule_high.evaluate(data=0.6).matched is False

    def test_rule_metadata_accessible(self):
        """Test that rule metadata is accessible."""
        rule = MockRule({"threshold": 0.5})

        assert rule.metadata.name == "test-mock-rule"
        assert rule.metadata.version == "1.0.0"
        assert rule.metadata.timeout_ms == 10

    def test_rule_config_stored(self):
        """Test that rule stores config."""
        config = {"threshold": 0.75, "extra": "value"}
        rule = MockRule(config)

        assert rule.config == config
        assert rule.threshold == 0.75


class TestRuleDiscovery:
    """Tests for rule discovery mechanism."""

    def setup_method(self):
        """Reset discovery state before each test."""
        clear_rules()
        reset_rule_discovery()

    def test_discover_rules_loads_builtins(self):
        """Test that discover_rules loads built-in rules."""
        discover_rules()

        rules = list_rules()
        assert "regex" in rules
        assert "list" in rules

    def test_discover_rules_only_runs_once(self):
        """Test that discovery only runs once."""
        count1 = discover_rules()
        count2 = discover_rules()

        # Second call should return 0 (already discovered)
        assert count2 == 0

    @patch("agent_control_rules._discovery.entry_points")
    def test_discover_rules_loads_entry_points(self, mock_entry_points):
        """Test loading rules via entry points."""
        mock_ep = MagicMock()
        mock_ep.name = "custom-rule"
        mock_ep.load.return_value = MockRule

        mock_entry_points.return_value = [mock_ep]

        discover_rules()

        mock_entry_points.assert_called_with(group="agent_control.rules")

    def test_ensure_rules_discovered_triggers_discovery(self):
        """Test that ensure_rules_discovered triggers discovery."""
        from agent_control.rules import ensure_rules_discovered

        ensure_rules_discovered()

        rules = list_rules()
        assert "regex" in rules
        assert "list" in rules
