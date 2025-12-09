"""Tests for plugin system integration with the unified architecture.

These tests verify the plugin system works correctly with the engine.
"""

import pytest
from typing import Any

from pydantic import BaseModel

from agent_control_models import (
    EvaluatorConfig,
    EvaluatorResult,
    PluginEvaluator,
    PluginMetadata,
    register_plugin,
    clear_plugins,
)
from agent_control_engine.evaluators import get_evaluator

# Import to ensure built-in plugins are registered
import agent_control_plugins  # noqa: F401


class MockConfig(BaseModel):
    """Config for mock plugin."""

    threshold: float = 0.5


class MockTestPlugin(PluginEvaluator[MockConfig]):
    """Mock plugin for engine testing."""

    metadata = PluginMetadata(
        name="test-mock-plugin",
        version="1.0.0",
        description="Test plugin for engine tests",
    )
    config_model = MockConfig

    def evaluate(self, data: Any) -> EvaluatorResult:
        """Mock evaluation."""
        value = float(data) if isinstance(data, (int, float)) else 0.0
        matched = value > self.config.threshold

        return EvaluatorResult(
            matched=matched,
            confidence=1.0,
            message=f"Value {value} vs threshold {self.config.threshold}",
            metadata={"value": value, "threshold": self.config.threshold},
        )


class TestPluginArchitecture:
    """Tests verifying the plugin architecture."""

    def test_plugin_is_abc_subclass(self):
        """Test PluginEvaluator is an ABC."""
        from abc import ABC

        assert issubclass(PluginEvaluator, ABC)

    def test_plugin_has_required_attributes(self):
        """Test plugins have required class attributes."""
        assert hasattr(MockTestPlugin, "metadata")
        assert hasattr(MockTestPlugin, "config_model")
        assert MockTestPlugin.metadata.name == "test-mock-plugin"

    def test_plugin_from_dict(self):
        """Test creating plugin from dict config."""
        plugin = MockTestPlugin.from_dict({"threshold": 0.7})

        assert isinstance(plugin.config, MockConfig)
        assert plugin.config.threshold == 0.7


class TestMockPluginEvaluation:
    """Tests for mock plugin evaluation."""

    @pytest.fixture(autouse=True)
    def register_mock(self):
        """Register mock plugin for tests."""
        register_plugin(MockTestPlugin)
        yield
        # Don't clear - other tests need built-in plugins

    def test_evaluate_matched(self):
        """Test evaluation when threshold exceeded."""
        config = EvaluatorConfig(plugin="test-mock-plugin", config={"threshold": 0.5})
        evaluator = get_evaluator(config)

        result = evaluator.evaluate(0.8)

        assert result.matched is True
        assert result.confidence == 1.0
        assert result.metadata["value"] == 0.8
        assert result.metadata["threshold"] == 0.5

    def test_evaluate_not_matched(self):
        """Test evaluation when below threshold."""
        config = EvaluatorConfig(plugin="test-mock-plugin", config={"threshold": 0.9})
        evaluator = get_evaluator(config)

        result = evaluator.evaluate(0.3)

        assert result.matched is False

    def test_multiple_evaluations(self):
        """Test multiple evaluations with same plugin."""
        config = EvaluatorConfig(plugin="test-mock-plugin", config={"threshold": 0.5})
        evaluator = get_evaluator(config)

        results = [
            evaluator.evaluate(0.2),
            evaluator.evaluate(0.6),
            evaluator.evaluate(0.9),
        ]

        assert results[0].matched is False  # 0.2 < 0.5
        assert results[1].matched is True  # 0.6 > 0.5
        assert results[2].matched is True  # 0.9 > 0.5


class TestPluginMetadata:
    """Tests for plugin metadata."""

    def test_access_metadata(self):
        """Test that plugin metadata is accessible."""
        assert MockTestPlugin.metadata.name == "test-mock-plugin"
        assert MockTestPlugin.metadata.version == "1.0.0"
        assert MockTestPlugin.metadata.description == "Test plugin for engine tests"

    def test_config_schema(self):
        """Test that config model provides JSON schema."""
        schema = MockTestPlugin.config_model.model_json_schema()

        assert "properties" in schema
        assert "threshold" in schema["properties"]


class TestBuiltInPlugins:
    """Tests for built-in plugins."""

    def test_regex_plugin_registered(self):
        """Test regex plugin is registered."""
        from agent_control_models import get_plugin

        plugin = get_plugin("regex")
        assert plugin is not None
        assert plugin.metadata.name == "regex"

    def test_list_plugin_registered(self):
        """Test list plugin is registered."""
        from agent_control_models import get_plugin

        plugin = get_plugin("list")
        assert plugin is not None
        assert plugin.metadata.name == "list"

    def test_custom_code_plugin_registered(self):
        """Test custom-code plugin is registered."""
        from agent_control_models import get_plugin

        plugin = get_plugin("custom-code")
        assert plugin is not None
        assert plugin.metadata.name == "custom-code"
