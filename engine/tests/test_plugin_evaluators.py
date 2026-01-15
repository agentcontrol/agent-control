"""Tests for plugin system integration with the unified architecture.

These tests verify the plugin system works correctly with the engine.
"""

from typing import Any

# Import to ensure built-in plugins are registered
import agent_control_plugins  # noqa: F401
import pytest
from agent_control_engine.evaluators import get_evaluator
from agent_control_models import (
    EvaluatorConfig,
    EvaluatorResult,
    PluginEvaluator,
    PluginMetadata,
    register_plugin,
)
from pydantic import BaseModel


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

    async def evaluate(self, data: Any) -> EvaluatorResult:
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
        # Given/When: Checking PluginEvaluator base class
        from abc import ABC

        # Then: Should be subclass of ABC
        assert issubclass(PluginEvaluator, ABC)

    def test_plugin_has_required_attributes(self):
        """Test plugins have required class attributes."""
        # Given/When: Checking MockTestPlugin
        # Then: Should have required attributes
        assert hasattr(MockTestPlugin, "metadata")
        assert hasattr(MockTestPlugin, "config_model")
        assert MockTestPlugin.metadata.name == "test-mock-plugin"

    def test_plugin_from_dict(self):
        """Test creating plugin from dict config."""
        # Given/When: Creating plugin from dict
        plugin = MockTestPlugin.from_dict({"threshold": 0.7})

        # Then: Config should be parsed correctly
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

    @pytest.mark.asyncio
    async def test_evaluate_matched(self):
        """Test evaluation when threshold exceeded."""
        # Given: Mock plugin with threshold 0.5
        config = EvaluatorConfig(plugin="test-mock-plugin", config={"threshold": 0.5})
        evaluator = get_evaluator(config)

        # When: Evaluating value above threshold
        result = await evaluator.evaluate(0.8)

        # Then: Should match with metadata
        assert result.matched is True
        assert result.confidence == 1.0
        assert result.metadata["value"] == 0.8
        assert result.metadata["threshold"] == 0.5

    @pytest.mark.asyncio
    async def test_evaluate_not_matched(self):
        """Test evaluation when below threshold."""
        # Given: Mock plugin with threshold 0.9
        config = EvaluatorConfig(plugin="test-mock-plugin", config={"threshold": 0.9})
        evaluator = get_evaluator(config)

        # When: Evaluating value below threshold
        result = await evaluator.evaluate(0.3)

        # Then: Should not match
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_multiple_evaluations(self):
        """Test multiple evaluations with same plugin."""
        # Given: Mock plugin with threshold 0.5
        config = EvaluatorConfig(plugin="test-mock-plugin", config={"threshold": 0.5})
        evaluator = get_evaluator(config)

        # When: Evaluating multiple values
        results = [
            await evaluator.evaluate(0.2),
            await evaluator.evaluate(0.6),
            await evaluator.evaluate(0.9),
        ]

        # Then: Results depend on threshold comparison
        assert results[0].matched is False  # 0.2 < 0.5
        assert results[1].matched is True  # 0.6 > 0.5
        assert results[2].matched is True  # 0.9 > 0.5


class TestPluginMetadata:
    """Tests for plugin metadata."""

    def test_access_metadata(self):
        """Test that plugin metadata is accessible."""
        # Given/When: Accessing MockTestPlugin metadata
        # Then: All fields should be correct
        assert MockTestPlugin.metadata.name == "test-mock-plugin"
        assert MockTestPlugin.metadata.version == "1.0.0"
        assert MockTestPlugin.metadata.description == "Test plugin for engine tests"

    def test_config_schema(self):
        """Test that config model provides JSON schema."""
        # Given/When: Getting JSON schema from config model
        schema = MockTestPlugin.config_model.model_json_schema()

        # Then: Schema should include threshold property
        assert "properties" in schema
        assert "threshold" in schema["properties"]


class TestBuiltInPlugins:
    """Tests for built-in plugins."""

    def test_regex_plugin_registered(self):
        """Test regex plugin is registered."""
        # Given/When: Getting regex plugin
        from agent_control_models import get_plugin
        plugin = get_plugin("regex")

        # Then: Should be registered with correct name
        assert plugin is not None
        assert plugin.metadata.name == "regex"

    def test_list_plugin_registered(self):
        """Test list plugin is registered."""
        # Given/When: Getting list plugin
        from agent_control_models import get_plugin
        plugin = get_plugin("list")

        # Then: Should be registered with correct name
        assert plugin is not None
        assert plugin.metadata.name == "list"


class TestRegexControlEvaluatorPluginFlags:
    """Tests for regex plugin flag handling."""

    @pytest.mark.asyncio
    async def test_regex_case_sensitive_by_default(self):
        """Test regex is case-sensitive by default.

        Given: A regex pattern without flags
        When: Evaluating against different case text
        Then: Only exact case matches
        """
        # Given: Regex for "SECRET" without flags
        config = EvaluatorConfig(
            plugin="regex",
            config={"pattern": "SECRET"}
        )
        evaluator = get_evaluator(config)

        # When/Then: Exact case matches
        result = await evaluator.evaluate("the SECRET is here")
        assert result.matched is True

        # When/Then: Different case does NOT match
        result = await evaluator.evaluate("the secret is here")
        assert result.matched is False

        result = await evaluator.evaluate("the Secret is here")
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_regex_ignorecase_flag(self):
        """Test regex IGNORECASE flag works.

        Given: A regex pattern with IGNORECASE flag
        When: Evaluating against different case text
        Then: All cases match
        """
        # Given: Regex for "SECRET" with IGNORECASE flag
        config = EvaluatorConfig(
            plugin="regex",
            config={"pattern": "SECRET", "flags": ["IGNORECASE"]}
        )
        evaluator = get_evaluator(config)

        # When/Then: All case variations should match
        result = await evaluator.evaluate("the SECRET is here")
        assert result.matched is True

        result = await evaluator.evaluate("the secret is here")
        assert result.matched is True

        result = await evaluator.evaluate("the Secret is here")
        assert result.matched is True

        result = await evaluator.evaluate("the sEcReT is here")
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_regex_short_i_flag(self):
        """Test regex short 'I' flag works.

        Given: A regex pattern with 'I' flag (short for IGNORECASE)
        When: Evaluating against different case text
        Then: All cases match
        """
        # Given: Regex with short "I" flag
        config = EvaluatorConfig(
            plugin="regex",
            config={"pattern": "password", "flags": ["I"]}
        )
        evaluator = get_evaluator(config)

        # When/Then: All case variations should match
        result = await evaluator.evaluate("PASSWORD")
        assert result.matched is True

        result = await evaluator.evaluate("password")
        assert result.matched is True

        result = await evaluator.evaluate("Password")
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_regex_ignorecase_lowercase_flag(self):
        """Test regex ignorecase flag works with lowercase.

        Given: A regex pattern with lowercase 'ignorecase' flag
        When: Evaluating against different case text
        Then: All cases match
        """
        # Given: Regex with lowercase flag variant
        config = EvaluatorConfig(
            plugin="regex",
            config={"pattern": "admin", "flags": ["ignorecase"]}
        )
        evaluator = get_evaluator(config)

        # When/Then: Should work with lowercase flag
        result = await evaluator.evaluate("ADMIN")
        assert result.matched is True

        result = await evaluator.evaluate("admin")
        assert result.matched is True

