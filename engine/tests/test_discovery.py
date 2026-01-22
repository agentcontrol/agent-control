"""Tests for plugin auto-discovery."""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_control_engine import discover_plugins, ensure_plugins_discovered, list_plugins
from agent_control_engine.discovery import reset_discovery
from agent_control_models import (
    EvaluatorResult,
    PluginEvaluator,
    PluginMetadata,
    clear_plugins,
    get_plugin,
    register_plugin,
)
from pydantic import BaseModel


class TestDiscoverPlugins:
    """Tests for discover_plugins() function."""

    def test_discover_plugins_loads_builtins(self) -> None:
        """Test that built-in plugins are loaded."""
        discover_plugins()

        plugins = list_plugins()
        assert "regex" in plugins
        assert "list" in plugins

    @patch("agent_control_engine.discovery.entry_points")
    def test_discover_plugins_loads_entry_points(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test that entry point plugins are discovered."""

        # Create mock plugin
        class MockConfig(BaseModel):
            pass

        class MockPlugin(PluginEvaluator[MockConfig]):
            metadata = PluginMetadata(
                name="mock-ep-plugin",
                version="1.0.0",
                description="Test plugin",
            )
            config_model = MockConfig

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=0.0, message="test")

        mock_ep = MagicMock()
        mock_ep.name = "mock-ep-plugin"
        mock_ep.load.return_value = MockPlugin
        mock_entry_points.return_value = [mock_ep]

        count = discover_plugins()

        mock_entry_points.assert_called_once_with(group="agent_control.plugins")
        plugins = list_plugins()
        assert "mock-ep-plugin" in plugins
        # Count only includes entry-point registrations (not built-ins loaded via import)
        assert count >= 1

    @patch("agent_control_engine.discovery.entry_points")
    def test_discover_plugins_handles_load_error(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test graceful handling of plugin load errors."""
        mock_ep = MagicMock()
        mock_ep.name = "bad-plugin"
        mock_ep.load.side_effect = ImportError("Missing dependency")
        mock_entry_points.return_value = [mock_ep]

        # Should not raise
        discover_plugins()

    def test_discover_plugins_only_runs_once(self) -> None:
        """Test that discovery only runs once."""
        count1 = discover_plugins()
        count2 = discover_plugins()

        # First call loads plugins, second call returns 0 (already discovered)
        assert count2 == 0
        # Verify plugins are available (count may be 0 if no entry-point plugins)
        plugins = list_plugins()
        assert "regex" in plugins
        assert "list" in plugins

    def test_ensure_plugins_discovered_triggers_discovery(self) -> None:
        """Test that ensure_plugins_discovered triggers discovery."""
        ensure_plugins_discovered()

        plugins = list_plugins()
        # Should have at least built-in plugins
        assert isinstance(plugins, dict)
        assert "regex" in plugins
        assert "list" in plugins

    def test_reset_discovery_allows_rediscovery(self) -> None:
        """Test that reset_discovery allows discovery to run again."""
        discover_plugins()
        plugins1 = list_plugins()
        assert "regex" in plugins1

        # After reset, discovery should run again
        reset_discovery()
        clear_plugins()

        discover_plugins()
        plugins2 = list_plugins()
        assert "regex" in plugins2
        assert "list" in plugins2

    @patch("agent_control_engine.discovery.entry_points")
    def test_discover_plugins_skips_unavailable(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test that plugins with is_available() returning False are skipped."""

        class MockConfig(BaseModel):
            pass

        class UnavailablePlugin(PluginEvaluator[MockConfig]):
            metadata = PluginMetadata(
                name="unavailable-plugin",
                version="1.0.0",
                description="Plugin with missing deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return False  # Simulate missing dependency

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=0.0, message="test")

        mock_ep = MagicMock()
        mock_ep.name = "unavailable-plugin"
        mock_ep.load.return_value = UnavailablePlugin
        mock_entry_points.return_value = [mock_ep]

        count = discover_plugins()

        # Plugin should NOT be registered
        plugins = list_plugins()
        assert "unavailable-plugin" not in plugins
        assert count == 0

    @patch("agent_control_engine.discovery.entry_points")
    def test_discover_plugins_registers_available(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Test that plugins with is_available() returning True are registered."""

        class MockConfig(BaseModel):
            pass

        class AvailablePlugin(PluginEvaluator[MockConfig]):
            metadata = PluginMetadata(
                name="available-plugin",
                version="1.0.0",
                description="Plugin with all deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return True

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=0.0, message="test")

        mock_ep = MagicMock()
        mock_ep.name = "available-plugin"
        mock_ep.load.return_value = AvailablePlugin
        mock_entry_points.return_value = [mock_ep]

        count = discover_plugins()

        # Plugin should be registered
        plugins = list_plugins()
        assert "available-plugin" in plugins
        assert count == 1


class TestIsAvailable:
    """Tests for the is_available() plugin method."""

    def test_base_class_is_available_returns_true(self) -> None:
        """Test that base PluginEvaluator.is_available() returns True by default."""

        class MockConfig(BaseModel):
            pass

        class TestPlugin(PluginEvaluator[MockConfig]):
            metadata = PluginMetadata(
                name="test-plugin",
                version="1.0.0",
                description="Test",
            )
            config_model = MockConfig

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=0.0, message="test")

        # Default is_available() should return True
        assert TestPlugin.is_available() is True


class TestRegisterPluginRespectsIsAvailable:
    """Tests that @register_plugin decorator respects is_available()."""

    def test_register_plugin_skips_unavailable(self) -> None:
        """Test that @register_plugin skips plugins where is_available() returns False."""

        class MockConfig(BaseModel):
            pass

        @register_plugin
        class UnavailablePlugin(PluginEvaluator[MockConfig]):
            metadata = PluginMetadata(
                name="test-unavailable-decorated",
                version="1.0.0",
                description="Plugin with unavailable deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return False  # Simulate missing dependency

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=0.0, message="test")

        # Plugin should NOT be registered despite using @register_plugin
        assert get_plugin("test-unavailable-decorated") is None

    def test_register_plugin_registers_available(self) -> None:
        """Test that @register_plugin registers plugins where is_available() returns True."""

        class MockConfig(BaseModel):
            pass

        @register_plugin
        class AvailablePlugin(PluginEvaluator[MockConfig]):
            metadata = PluginMetadata(
                name="test-available-decorated",
                version="1.0.0",
                description="Plugin with all deps",
            )
            config_model = MockConfig

            @classmethod
            def is_available(cls) -> bool:
                return True

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=0.0, message="test")

        # Plugin should be registered
        assert get_plugin("test-available-decorated") is not None

    def test_register_plugin_default_is_available(self) -> None:
        """Test that @register_plugin works when is_available() is not overridden."""

        class MockConfig(BaseModel):
            pass

        @register_plugin
        class DefaultPlugin(PluginEvaluator[MockConfig]):
            metadata = PluginMetadata(
                name="test-default-available",
                version="1.0.0",
                description="Plugin with default is_available",
            )
            config_model = MockConfig

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(matched=False, confidence=0.0, message="test")

        # Plugin should be registered (default is_available returns True)
        assert get_plugin("test-default-available") is not None
