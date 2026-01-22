"""Unit tests for the plugin system.

Tests plugin registration, discovery, and base functionality without
requiring actual plugin implementations or external services.

New architecture: Plugins take config at __init__, evaluate() only takes data.
Registry is now in agent_control_models, discovery in agent_control_engine.
"""

from unittest.mock import MagicMock, patch

import pytest
from agent_control_engine.discovery import reset_discovery
from agent_control_models import clear_plugins
from agent_control_models.controls import EvaluatorResult
from pydantic import BaseModel

from agent_control.plugins import (
    PluginEvaluator,
    PluginMetadata,
    discover_plugins,
    list_plugins,
    register_plugin,
)


class MockConfig(BaseModel):
    """Config model for MockPlugin."""
    threshold: float = 0.5


class MockPlugin(PluginEvaluator):
    """Mock plugin for testing.

    New pattern: config is passed at __init__, not at evaluate().
    """

    metadata = PluginMetadata(
        name="test-mock-plugin",
        version="1.0.0",
        description="Mock plugin for testing",
        requires_api_key=False,
        timeout_ms=10,
    )
    config_model = MockConfig

    def __init__(self, config: dict):
        super().__init__(config)
        self.threshold = config.get("threshold", 0.5)

    def evaluate(self, data) -> EvaluatorResult:
        """Mock evaluation (synchronous)."""
        matched = float(data) > self.threshold if isinstance(data, (int, float)) else False
        return EvaluatorResult(
            matched=matched,
            confidence=1.0,
            message=f"Mock evaluation: {matched}",
            metadata={"threshold": self.threshold},
        )


class TestPluginMetadata:
    """Tests for PluginMetadata dataclass."""

    def test_metadata_creation(self):
        """Test creating plugin metadata."""
        metadata = PluginMetadata(
            name="test-plugin",
            version="1.0.0",
            description="Test plugin",
        )

        assert metadata.name == "test-plugin"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test plugin"
        assert metadata.requires_api_key is False
        assert metadata.timeout_ms == 10000  # Default

    def test_metadata_with_all_fields(self):
        """Test metadata with all fields populated."""
        metadata = PluginMetadata(
            name="full-plugin",
            version="2.0.0",
            description="Full test",
            requires_api_key=True,
            timeout_ms=5000,
        )

        assert metadata.requires_api_key is True
        assert metadata.timeout_ms == 5000


class TestPluginRegistry:
    """Tests for plugin registry functionality."""

    def setup_method(self):
        """Clear registry before each test."""
        # Clear all plugins and reset discovery
        clear_plugins()
        reset_discovery()
        # Run discovery to load built-in plugins
        discover_plugins()

    def test_register_plugin(self):
        """Test registering a plugin."""
        # Register mock plugin
        register_plugin(MockPlugin)

        # Verify it's registered
        plugin_class = list_plugins().get("test-mock-plugin")
        assert plugin_class is MockPlugin

    def test_get_nonexistent_plugin(self):
        """Test getting a plugin that doesn't exist."""
        plugin_class = list_plugins().get("nonexistent-plugin-xyz")
        assert plugin_class is None

    def test_list_plugins_includes_registered(self):
        """Test listing plugins includes registered plugins."""
        # Register mock plugin
        register_plugin(MockPlugin)

        # List plugins - now returns dict of plugin classes
        plugins = list_plugins()

        assert "test-mock-plugin" in plugins
        assert plugins["test-mock-plugin"] is MockPlugin

    def test_builtin_plugins_available(self):
        """Test that built-in plugins are available after discovery."""
        plugins = list_plugins()

        assert "regex" in plugins
        assert "list" in plugins

    def test_register_duplicate_plugin_raises_error(self):
        """Test that registering a different plugin with same name raises ValueError."""
        # Register plugin first
        register_plugin(MockPlugin)

        # Create a different class with the same plugin name
        class DuplicatePlugin(PluginEvaluator):
            metadata = PluginMetadata(
                name="test-mock-plugin",  # Same name as MockPlugin
                version="2.0.0",
                description="Duplicate plugin",
            )
            config_model = MockConfig

            def evaluate(self, data) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=1.0, message="duplicate")

        # Second registration with different class should fail
        with pytest.raises(ValueError, match="already registered"):
            register_plugin(DuplicatePlugin)

    def test_re_register_same_plugin_allowed(self):
        """Test that re-registering the same class is allowed (hot reload support)."""
        register_plugin(MockPlugin)
        # Should not raise - same class can be re-registered
        result = register_plugin(MockPlugin)
        assert result is MockPlugin


class TestPluginEvaluator:
    """Tests for PluginEvaluator base class."""

    def test_plugin_evaluate(self):
        """Test synchronous evaluation."""
        # Config is now passed at init
        plugin = MockPlugin({"threshold": 0.5})
        result = plugin.evaluate(data=0.8)

        assert isinstance(result, EvaluatorResult)
        assert result.matched is True
        assert result.confidence == 1.0
        assert "Mock evaluation" in result.message

    def test_plugin_evaluate_no_match(self):
        """Test evaluation when rule doesn't match."""
        plugin = MockPlugin({"threshold": 0.5})
        result = plugin.evaluate(data=0.3)

        assert isinstance(result, EvaluatorResult)
        assert result.matched is False
        assert result.confidence == 1.0

    def test_plugin_with_different_configs(self):
        """Test plugin uses config correctly (set at init)."""
        # Create two plugins with different configs
        plugin_low = MockPlugin({"threshold": 0.5})
        plugin_high = MockPlugin({"threshold": 0.7})

        # Same data, different thresholds
        assert plugin_low.evaluate(data=0.6).matched is True
        assert plugin_high.evaluate(data=0.6).matched is False

    def test_plugin_metadata_accessible(self):
        """Test that plugin metadata is accessible."""
        plugin = MockPlugin({"threshold": 0.5})

        assert plugin.metadata.name == "test-mock-plugin"
        assert plugin.metadata.version == "1.0.0"
        assert plugin.metadata.timeout_ms == 10

    def test_plugin_config_stored(self):
        """Test that plugin stores config."""
        config = {"threshold": 0.75, "extra": "value"}
        plugin = MockPlugin(config)

        assert plugin.config == config
        assert plugin.threshold == 0.75


class TestPluginDiscovery:
    """Tests for plugin discovery mechanism."""

    def setup_method(self):
        """Reset discovery state before each test."""
        clear_plugins()
        reset_discovery()

    def test_discover_plugins_loads_builtins(self):
        """Test that discover_plugins loads built-in plugins."""
        discover_plugins()

        plugins = list_plugins()
        assert "regex" in plugins
        assert "list" in plugins

    def test_discover_plugins_only_runs_once(self):
        """Test that discovery only runs once."""
        count1 = discover_plugins()
        count2 = discover_plugins()

        # Second call should return 0 (already discovered)
        assert count2 == 0

    @patch("agent_control_engine.discovery.entry_points")
    def test_discover_plugins_loads_entry_points(self, mock_entry_points):
        """Test loading plugins via entry points."""
        mock_ep = MagicMock()
        mock_ep.name = "custom-plugin"
        mock_ep.load.return_value = MockPlugin

        mock_entry_points.return_value = [mock_ep]

        discover_plugins()

        mock_entry_points.assert_called_with(group="agent_control.plugins")

    def test_ensure_plugins_discovered_triggers_discovery(self):
        """Test that ensure_plugins_discovered triggers discovery."""
        from agent_control.plugins import ensure_plugins_discovered

        ensure_plugins_discovered()

        plugins = list_plugins()
        assert "regex" in plugins
        assert "list" in plugins
