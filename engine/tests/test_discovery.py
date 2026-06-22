"""Tests for rule auto-discovery."""

from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from agent_control_engine import (
    discover_rules,
    ensure_rules_discovered,
    list_rules,
    reset_rule_discovery,
)
from agent_control_rules import (
    Rule,
    RuleMetadata,
    clear_rules,
    get_rule,
    register_rule,
)
from agent_control_models import RuleResult


class TestDiscoverRules:
    """Tests for discover_rules() function."""

    def test_discover_rules_loads_builtins(self) -> None:
        """Test that built-in rules are loaded."""
        discover_rules()

        rules = list_rules()
        assert "regex" in rules
        assert "list" in rules

    @patch("agent_control_rules._discovery.entry_points")
    def test_discover_rules_loads_entry_points(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test that entry point rules are discovered."""

        # Create mock rule
        class MockConfig(BaseModel):
            pass

        class MockRule(Rule[MockConfig]):
            metadata = RuleMetadata(
                name="mock-ep-rule",
                version="1.0.0",
                description="Test rule",
            )
            config_model = MockConfig

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(matched=False, confidence=0.0, message="test")

        mock_ep = MagicMock()
        mock_ep.name = "mock-ep-rule"
        mock_ep.load.return_value = MockRule
        mock_entry_points.return_value = [mock_ep]

        count = discover_rules()

        mock_entry_points.assert_called_once_with(group="agent_control.rules")
        rules = list_rules()
        assert "mock-ep-rule" in rules
        # Count only includes entry-point registrations (not built-ins loaded via import)
        assert count >= 1

    @patch("agent_control_rules._discovery.entry_points")
    def test_discover_rules_handles_load_error(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test graceful handling of rule load errors."""
        mock_ep = MagicMock()
        mock_ep.name = "bad-rule"
        mock_ep.load.side_effect = ImportError("Missing dependency")
        mock_entry_points.return_value = [mock_ep]

        # Should not raise
        discover_rules()

    def test_discover_rules_only_runs_once(self) -> None:
        """Test that discovery only runs once."""
        count1 = discover_rules()
        count2 = discover_rules()

        # First call loads rules, second call returns 0 (already discovered)
        assert count2 == 0
        # Verify rules are available (count may be 0 if no entry-point rules)
        rules = list_rules()
        assert "regex" in rules
        assert "list" in rules

    def test_ensure_rules_discovered_triggers_discovery(self) -> None:
        """Test that ensure_rules_discovered triggers discovery."""
        ensure_rules_discovered()

        rules = list_rules()
        # Should have at least built-in rules
        assert isinstance(rules, dict)
        assert "regex" in rules
        assert "list" in rules

    def test_reset_rule_discovery_allows_rediscovery(self) -> None:
        """Test that reset_rule_discovery allows discovery to run again."""
        discover_rules()
        rules1 = list_rules()
        assert "regex" in rules1

        # After reset, discovery should run again
        reset_rule_discovery()
        clear_rules()

        discover_rules()
        rules2 = list_rules()
        assert "regex" in rules2
        assert "list" in rules2

    @patch("agent_control_rules._discovery.entry_points")
    def test_discover_rules_skips_unavailable(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test that rules with is_available() returning False are skipped."""

        class MockConfig(BaseModel):
            pass

        class UnavailableRule(Rule[MockConfig]):
            metadata = RuleMetadata(
                name="unavailable-rule",
                version="1.0.0",
                description="Rule with missing deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return False  # Simulate missing dependency

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(matched=False, confidence=0.0, message="test")

        mock_ep = MagicMock()
        mock_ep.name = "unavailable-rule"
        mock_ep.load.return_value = UnavailableRule
        mock_entry_points.return_value = [mock_ep]

        count = discover_rules()

        # Rule should NOT be registered
        rules = list_rules()
        assert "unavailable-rule" not in rules
        assert count == 0

    @patch("agent_control_rules._discovery.entry_points")
    def test_discover_rules_registers_available(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test that rules with is_available() returning True are registered."""

        class MockConfig(BaseModel):
            pass

        class AvailableRule(Rule[MockConfig]):
            metadata = RuleMetadata(
                name="available-rule",
                version="1.0.0",
                description="Rule with all deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return True

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(matched=False, confidence=0.0, message="test")

        mock_ep = MagicMock()
        mock_ep.name = "available-rule"
        mock_ep.load.return_value = AvailableRule
        mock_entry_points.return_value = [mock_ep]

        count = discover_rules()

        # Rule should be registered
        rules = list_rules()
        assert "available-rule" in rules
        assert count == 1


class TestIsAvailable:
    """Tests for the is_available() rule method."""

    def test_base_class_is_available_returns_true(self) -> None:
        """Test that base Rule.is_available() returns True by default."""

        class MockConfig(BaseModel):
            pass

        class TestRule(Rule[MockConfig]):
            metadata = RuleMetadata(
                name="test-rule",
                version="1.0.0",
                description="Test",
            )
            config_model = MockConfig

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(matched=False, confidence=0.0, message="test")

        # Default is_available() should return True
        assert TestRule.is_available() is True


class TestRegisterRuleRespectsIsAvailable:
    """Tests that @register_rule decorator respects is_available()."""

    def test_register_rule_skips_unavailable(self) -> None:
        """Test that @register_rule skips rules where is_available() returns False."""

        class MockConfig(BaseModel):
            pass

        @register_rule
        class UnavailableRule(Rule[MockConfig]):
            metadata = RuleMetadata(
                name="test-unavailable-decorated",
                version="1.0.0",
                description="Rule with unavailable deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return False  # Simulate missing dependency

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(matched=False, confidence=0.0, message="test")

        # Rule should NOT be registered despite using @register_rule
        assert get_rule("test-unavailable-decorated") is None

    def test_register_rule_registers_available(self) -> None:
        """Test that @register_rule registers rules where is_available() returns True."""

        class MockConfig(BaseModel):
            pass

        @register_rule
        class AvailableRule(Rule[MockConfig]):
            metadata = RuleMetadata(
                name="test-available-decorated",
                version="1.0.0",
                description="Rule with all deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return True

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(matched=False, confidence=0.0, message="test")

        # Rule should be registered
        assert get_rule("test-available-decorated") is not None

    def test_register_rule_default_is_available(self) -> None:
        """Test that @register_rule works when is_available() is not overridden."""

        class MockConfig(BaseModel):
            pass

        @register_rule
        class DefaultRule(Rule[MockConfig]):
            metadata = RuleMetadata(
                name="test-default-available",
                version="1.0.0",
                description="Rule with default is_available",
            )
            config_model = MockConfig

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(matched=False, confidence=0.0, message="test")

        # Rule should be registered (default is_available returns True)
        assert get_rule("test-default-available") is not None
