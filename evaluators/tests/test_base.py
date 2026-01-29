"""Tests for evaluator base classes.

Architecture: Evaluators take config at __init__, evaluate() only takes data.
"""

import pytest
from typing import Any

from agent_control_evaluators import Evaluator, EvaluatorConfig, EvaluatorMetadata
from agent_control_models import EvaluatorResult


class MockConfig(EvaluatorConfig):
    """Config model for mock evaluator."""

    should_match: bool = False
    timeout_ms: int = 5000


class MockEvaluator(Evaluator[MockConfig]):
    """A mock evaluator for testing."""

    metadata = EvaluatorMetadata(
        name="mock-evaluator",
        version="1.0.0",
        description="A mock evaluator for testing",
        requires_api_key=False,
        timeout_ms=5000,
    )
    config_model = MockConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Simple mock evaluation."""
        return EvaluatorResult(
            matched=self.config.should_match,
            confidence=1.0,
            message="Mock evaluation",
            metadata={"data": str(data)},
        )


class TestEvaluatorMetadata:
    """Tests for EvaluatorMetadata dataclass."""

    def test_metadata_with_defaults(self):
        """Test metadata with default values."""
        metadata = EvaluatorMetadata(
            name="test-evaluator",
            version="1.0.0",
            description="Test evaluator",
        )

        assert metadata.name == "test-evaluator"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test evaluator"
        assert metadata.requires_api_key is False
        assert metadata.timeout_ms == 10000

    def test_metadata_with_all_fields(self):
        """Test metadata with all fields specified."""
        metadata = EvaluatorMetadata(
            name="full-evaluator",
            version="2.0.0",
            description="Full evaluator",
            requires_api_key=True,
            timeout_ms=15000,
        )

        assert metadata.name == "full-evaluator"
        assert metadata.version == "2.0.0"
        assert metadata.requires_api_key is True
        assert metadata.timeout_ms == 15000


class TestEvaluator:
    """Tests for Evaluator base class."""

    def test_evaluator_is_abstract(self):
        """Test that Evaluator is an ABC."""
        from abc import ABC
        assert issubclass(Evaluator, ABC)

    def test_mock_evaluator_metadata(self):
        """Test that mock evaluator has correct metadata."""
        assert MockEvaluator.metadata.name == "mock-evaluator"
        assert MockEvaluator.metadata.version == "1.0.0"
        assert MockEvaluator.metadata.timeout_ms == 5000

    @pytest.mark.asyncio
    async def test_mock_evaluator_evaluate(self):
        """Test mock evaluator evaluation."""
        evaluator = MockEvaluator.from_dict({"should_match": True})

        result = await evaluator.evaluate("test data")

        assert result.matched is True
        assert result.confidence == 1.0
        assert result.metadata["data"] == "test data"

    @pytest.mark.asyncio
    async def test_mock_evaluator_evaluate_no_match(self):
        """Test mock evaluator evaluation without match."""
        evaluator = MockEvaluator.from_dict({"should_match": False})

        result = await evaluator.evaluate("test data")

        assert result.matched is False

    def test_evaluator_config_stored(self):
        """Test that evaluator stores config."""
        evaluator = MockEvaluator.from_dict({"should_match": True})

        assert isinstance(evaluator.config, MockConfig)
        assert evaluator.config.should_match is True

    def test_get_timeout_seconds_from_config(self):
        """Test timeout conversion from config."""
        evaluator = MockEvaluator.from_dict({"timeout_ms": 3000})

        assert evaluator.get_timeout_seconds() == 3.0

    def test_get_timeout_seconds_different_values(self):
        """Test timeout with different values."""
        evaluator1 = MockEvaluator.from_dict({"timeout_ms": 7500})
        evaluator2 = MockEvaluator.from_dict({"timeout_ms": 1000})

        assert evaluator1.get_timeout_seconds() == 7.5
        assert evaluator2.get_timeout_seconds() == 1.0

    def test_get_timeout_seconds_from_default(self):
        """Test timeout uses metadata default when not in config."""
        evaluator = MockEvaluator.from_dict({})  # No timeout_ms in config

        # MockConfig has default timeout_ms=5000
        assert evaluator.get_timeout_seconds() == 5.0

    def test_cannot_instantiate_abstract_class(self):
        """Test that Evaluator cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            Evaluator({})  # type: ignore
