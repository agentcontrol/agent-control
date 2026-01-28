"""Tests for evaluator system integration with the unified architecture.

These tests verify the evaluator system works correctly with the engine.
"""

from typing import Any

# Import to ensure built-in evaluators are registered
import agent_control_evaluators  # noqa: F401
import pytest
from agent_control_engine.evaluators import get_evaluator_instance
from agent_control_models import (
    Evaluator,
    EvaluatorConfig,
    EvaluatorMetadata,
    EvaluatorResult,
    register_evaluator,
)
from pydantic import BaseModel


class MockConfig(BaseModel):
    """Config for mock evaluator."""

    threshold: float = 0.5


class MockTestEvaluator(Evaluator[MockConfig]):
    """Mock evaluator for engine testing."""

    metadata = EvaluatorMetadata(
        name="test-mock-evaluator",
        version="1.0.0",
        description="Test evaluator for engine tests",
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


class TestEvaluatorArchitecture:
    """Tests verifying the evaluator architecture."""

    def test_evaluator_is_abc_subclass(self):
        """Test Evaluator is an ABC."""
        # Given/When: Checking Evaluator base class
        from abc import ABC

        # Then: Should be subclass of ABC
        assert issubclass(Evaluator, ABC)

    def test_evaluator_has_required_attributes(self):
        """Test evaluators have required class attributes."""
        # Given/When: Checking MockTestEvaluator
        # Then: Should have required attributes
        assert hasattr(MockTestEvaluator, "metadata")
        assert hasattr(MockTestEvaluator, "config_model")
        assert MockTestEvaluator.metadata.name == "test-mock-evaluator"

    def test_evaluator_from_dict(self):
        """Test creating evaluator from dict config."""
        # Given/When: Creating evaluator from dict
        evaluator = MockTestEvaluator.from_dict({"threshold": 0.7})

        # Then: Config should be parsed correctly
        assert isinstance(evaluator.config, MockConfig)
        assert evaluator.config.threshold == 0.7


class TestMockEvaluatorEvaluation:
    """Tests for mock evaluator evaluation."""

    @pytest.fixture(autouse=True)
    def register_mock(self):
        """Register mock evaluator for tests."""
        register_evaluator(MockTestEvaluator)
        yield
        # Don't clear - other tests need built-in evaluators

    @pytest.mark.asyncio
    async def test_evaluate_matched(self):
        """Test evaluation when threshold exceeded."""
        # Given: Mock evaluator with threshold 0.5
        config = EvaluatorConfig(name="test-mock-evaluator", config={"threshold": 0.5})
        evaluator = get_evaluator_instance(config)

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
        # Given: Mock evaluator with threshold 0.9
        config = EvaluatorConfig(name="test-mock-evaluator", config={"threshold": 0.9})
        evaluator = get_evaluator_instance(config)

        # When: Evaluating value below threshold
        result = await evaluator.evaluate(0.3)

        # Then: Should not match
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_multiple_evaluations(self):
        """Test multiple evaluations with same evaluator."""
        # Given: Mock evaluator with threshold 0.5
        config = EvaluatorConfig(name="test-mock-evaluator", config={"threshold": 0.5})
        evaluator = get_evaluator_instance(config)

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


class TestEvaluatorMetadata:
    """Tests for evaluator metadata."""

    def test_access_metadata(self):
        """Test that evaluator metadata is accessible."""
        # Given/When: Accessing MockTestEvaluator metadata
        # Then: All fields should be correct
        assert MockTestEvaluator.metadata.name == "test-mock-evaluator"
        assert MockTestEvaluator.metadata.version == "1.0.0"
        assert MockTestEvaluator.metadata.description == "Test evaluator for engine tests"

    def test_config_schema(self):
        """Test that config model provides JSON schema."""
        # Given/When: Getting JSON schema from config model
        schema = MockTestEvaluator.config_model.model_json_schema()

        # Then: Schema should include threshold property
        assert "properties" in schema
        assert "threshold" in schema["properties"]


class TestBuiltInEvaluators:
    """Tests for built-in evaluators."""

    def test_regex_evaluator_registered(self):
        """Test regex evaluator is registered."""
        # Given/When: Getting regex evaluator
        from agent_control_engine import list_evaluators
        evaluator = list_evaluators().get("regex")

        # Then: Should be registered with correct name
        assert evaluator is not None
        assert evaluator.metadata.name == "regex"

    def test_list_evaluator_registered(self):
        """Test list evaluator is registered."""
        # Given/When: Getting list evaluator
        from agent_control_engine import list_evaluators
        evaluator = list_evaluators().get("list")

        # Then: Should be registered with correct name
        assert evaluator is not None
        assert evaluator.metadata.name == "list"


class TestRegexEvaluatorFlags:
    """Tests for regex evaluator flag handling."""

    @pytest.mark.asyncio
    async def test_regex_case_sensitive_by_default(self):
        """Test regex is case-sensitive by default.

        Given: A regex pattern without flags
        When: Evaluating against different case text
        Then: Only exact case matches
        """
        # Given: Regex for "SECRET" without flags
        config = EvaluatorConfig(
            name="regex",
            config={"pattern": "SECRET"}
        )
        evaluator = get_evaluator_instance(config)

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
            name="regex",
            config={"pattern": "SECRET", "flags": ["IGNORECASE"]}
        )
        evaluator = get_evaluator_instance(config)

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
            name="regex",
            config={"pattern": "password", "flags": ["I"]}
        )
        evaluator = get_evaluator_instance(config)

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
            name="regex",
            config={"pattern": "admin", "flags": ["ignorecase"]}
        )
        evaluator = get_evaluator_instance(config)

        # When/Then: Should work with lowercase flag
        result = await evaluator.evaluate("ADMIN")
        assert result.matched is True

        result = await evaluator.evaluate("admin")
        assert result.matched is True
