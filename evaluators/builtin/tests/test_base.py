"""Tests for evaluator base classes.

Architecture:
    - ``evaluate(data)`` is the abstract entry point every subclass implements.
    - ``evaluate_with_context(data, context)`` is the context-aware entry the
      engine uses; the default delegates to ``evaluate(data)`` so legacy
      subclasses keep working without modification.
"""

import pytest
from typing import Any

from agent_control_evaluators import (
    EvaluationContext,
    Evaluator,
    EvaluatorConfig,
    EvaluatorMetadata,
)
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


class TestEvaluateWithContext:
    """Tests for the context-aware entry point on the base Evaluator."""

    @pytest.mark.asyncio
    async def test_default_evaluate_with_context_delegates_to_evaluate(self):
        """A subclass that only implements ``evaluate`` is still reachable
        through ``evaluate_with_context``.
        """
        evaluator = MockEvaluator.from_dict({"should_match": True})

        result = await evaluator.evaluate_with_context("payload")

        # The legacy ``evaluate`` returns matched=True and stores the data
        # in metadata. If the default fallback worked, those carry through.
        assert result.matched is True
        assert result.metadata["data"] == "payload"

    @pytest.mark.asyncio
    async def test_default_evaluate_with_context_ignores_context(self):
        """The default forwarder drops the context when it calls ``evaluate``
        — this is by design so legacy implementations are unaffected.
        """
        evaluator = MockEvaluator.from_dict({"should_match": False})

        context = EvaluationContext(
            target_type="log_stream",
            target_id="ls-123",
            agent_name="acme",
            step_type="llm",
        )

        # Should not raise, even though MockEvaluator.evaluate has no kwargs
        # for context. The default forwarder strips it.
        result = await evaluator.evaluate_with_context("data", context)

        assert result.matched is False
        assert result.metadata["data"] == "data"

    @pytest.mark.asyncio
    async def test_subclass_can_override_evaluate_with_context(self):
        """A subclass override of ``evaluate_with_context`` is preferred over
        the default fallback when the engine calls it.
        """

        class ContextAwareConfig(EvaluatorConfig):
            pass

        class ContextAware(Evaluator[ContextAwareConfig]):
            metadata = EvaluatorMetadata(
                name="ctx-aware",
                version="1.0.0",
                description="",
            )
            config_model = ContextAwareConfig

            async def evaluate(self, data: Any) -> EvaluatorResult:
                # Canonical "no-context" delegate pattern.
                return await self.evaluate_with_context(data, context=None)

            async def evaluate_with_context(
                self,
                data: Any,
                context: EvaluationContext | None = None,
            ) -> EvaluatorResult:
                target_id = context.target_id if context else "no-target"
                return EvaluatorResult(
                    matched=True,
                    confidence=1.0,
                    message=f"saw {target_id}",
                )

        evaluator = ContextAware.from_dict({})

        ctx = EvaluationContext(target_type="log_stream", target_id="ls-7")
        result = await evaluator.evaluate_with_context("data", ctx)
        assert result.message == "saw ls-7"

        # The Luna-pattern ``evaluate`` should also work as the no-context path.
        result_no_ctx = await evaluator.evaluate("data")
        assert result_no_ctx.message == "saw no-target"

    @pytest.mark.asyncio
    async def test_evaluation_context_defaults_are_none(self):
        """All EvaluationContext fields default to None and the dataclass is
        constructible with no arguments. Regression guard against orphan
        fields that have no populator on the engine side.
        """
        ctx = EvaluationContext()
        assert ctx.target_type is None
        assert ctx.target_id is None
        assert ctx.agent_name is None
        assert ctx.step_type is None
        # Confirm we did not silently keep namespace_key around; reading an
        # unknown attribute should fail.
        with pytest.raises(AttributeError):
            _ = ctx.namespace_key  # type: ignore[attr-defined]

    def test_evaluation_context_is_importable_from_evaluators_package(self):
        """EvaluationContext is re-exported from agent_control_evaluators so
        subclasses can colocate their imports.
        """
        from agent_control_evaluators import EvaluationContext as Reexported
        from agent_control_models import EvaluationContext as Canonical

        assert Reexported is Canonical
