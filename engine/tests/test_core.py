"""Tests for ControlEngine parallel evaluation and cancel-on-deny.

These tests verify:
1. Controls are evaluated in parallel (not sequentially)
2. On first deny, remaining controls are cancelled
3. Results are collected correctly from completed evaluations
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from agent_control_engine import clear_evaluator_cache
from agent_control_engine.core import ControlEngine, _compile_regex
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import (
    ControlAction,
    ControlDefinition,
    EvaluationRequest,
    EvaluatorResult,
    EvaluatorSpec,
    SteeringContext,
    Step,
)
from pydantic import BaseModel

# =============================================================================
# Test Fixtures and Helpers
# =============================================================================


class SimpleConfig(BaseModel):
    """Simple config for test evaluators."""

    value: str = "default"


# Shared state for coordination between test evaluators
_execution_log: list[str] = []
_blocker_event: asyncio.Event | None = None


def reset_test_state() -> None:
    """Reset shared test state."""
    global _execution_log, _blocker_event
    _execution_log = []
    _blocker_event = asyncio.Event()


class AllowEvaluator(Evaluator[SimpleConfig]):
    """Evaluator that always allows (matched=False)."""

    metadata = EvaluatorMetadata(
        name="test-allow",
        version="1.0.0",
        description="Always allows",
    )
    config_model = SimpleConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        _execution_log.append(f"allow:{self.config.value}:start")
        result = EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="Allowed",
        )
        _execution_log.append(f"allow:{self.config.value}:end")
        return result


class DenyEvaluator(Evaluator[SimpleConfig]):
    """Evaluator that always denies (matched=True)."""

    metadata = EvaluatorMetadata(
        name="test-deny",
        version="1.0.0",
        description="Always denies",
    )
    config_model = SimpleConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        _execution_log.append(f"deny:{self.config.value}:start")
        result = EvaluatorResult(
            matched=True,
            confidence=1.0,
            message="Denied",
        )
        _execution_log.append(f"deny:{self.config.value}:end")
        return result


class BlockerEvaluator(Evaluator[SimpleConfig]):
    """Evaluator that blocks until cancelled or event is set.

    Used to test cancellation behavior.
    """

    metadata = EvaluatorMetadata(
        name="test-blocker",
        version="1.0.0",
        description="Blocks until cancelled",
    )
    config_model = SimpleConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        _execution_log.append(f"blocker:{self.config.value}:start")
        try:
            # Wait indefinitely (should be cancelled)
            await _blocker_event.wait()  # type: ignore
            _execution_log.append(f"blocker:{self.config.value}:end")
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Blocker completed (should not happen in cancel test)",
            )
        except asyncio.CancelledError:
            _execution_log.append(f"blocker:{self.config.value}:cancelled")
            raise


class SlowEvaluator(Evaluator[SimpleConfig]):
    """Evaluator that sleeps briefly before returning."""

    metadata = EvaluatorMetadata(
        name="test-slow",
        version="1.0.0",
        description="Sleeps then allows",
    )
    config_model = SimpleConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        _execution_log.append(f"slow:{self.config.value}:start")
        await asyncio.sleep(0.05)  # 50ms
        _execution_log.append(f"slow:{self.config.value}:end")
        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="Slow completed",
        )


class MetadataEvaluator(Evaluator[SimpleConfig]):
    """Evaluator that emits structured metadata for propagation tests."""

    metadata = EvaluatorMetadata(
        name="test-metadata",
        version="1.0.0",
        description="Returns metadata while matching by config prefix",
    )
    config_model = SimpleConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        _execution_log.append(f"metadata:{self.config.value}:start")
        matched = self.config.value.startswith("match")
        result = EvaluatorResult(
            matched=matched,
            confidence=0.8 if matched else 0.4,
            message=f"Metadata {self.config.value}",
            metadata={"source": self.config.value, "selected_data": data},
        )
        _execution_log.append(f"metadata:{self.config.value}:end")
        return result


@dataclass
class MockControlWithIdentity:
    """Mock control for testing."""

    id: int
    name: str
    control: ControlDefinition


@pytest.fixture(autouse=True)
def setup_test_evaluators():
    """Register test evaluators and reset state before each test."""
    reset_test_state()
    clear_evaluator_cache()

    # Register evaluators (may already be registered)
    for evaluator_cls in [
        AllowEvaluator,
        DenyEvaluator,
        BlockerEvaluator,
        SlowEvaluator,
        MetadataEvaluator,
    ]:
        try:
            register_evaluator(evaluator_cls)
        except ValueError:
            pass  # Already registered

    yield

    reset_test_state()
    clear_evaluator_cache()


def make_control(
    control_id: int,
    name: str,
    evaluator: str,
    action: str = "deny",
    config_value: str = "default",
    *,
    step_types: list[str] | None = None,
    stages: list[str] | None = None,
    path: str | None = "input",
    step_names: list[str] | None = None,
    step_name_regex: str | None = None,
    execution: str = "server",
    steering_context: SteeringContext | None = None,
) -> MockControlWithIdentity:
    """Create a mock control for testing."""
    selector: dict[str, Any] = {}
    if path is not None:
        selector["path"] = path
    scope: dict[str, Any] = {}
    if step_types is None:
        step_types = ["llm"]
    scope["step_types"] = step_types
    if step_names is not None:
        scope["step_names"] = step_names
    if step_name_regex is not None:
        scope["step_name_regex"] = step_name_regex
    if stages is None:
        stages = ["pre"]
    if stages is not None:
        scope["stages"] = stages

    return MockControlWithIdentity(
        id=control_id,
        name=name,
        control=ControlDefinition(
            description=f"Test control {name}",
            enabled=True,
            execution=execution,
            scope=scope,
            condition={
                "selector": selector or {"path": "*"},
                "evaluator": EvaluatorSpec(
                    name=evaluator,
                    config={"value": config_value},
                ),
            },
            action=(
                ControlAction(decision=action, steering_context=steering_context)
                if steering_context
                else ControlAction(decision=action)
            ),
        ),
    )


# =============================================================================
# Test: Parallel Execution
# =============================================================================


class TestParallelExecution:
    """Tests verifying controls are evaluated in parallel."""

    @pytest.mark.asyncio
    async def test_parallel_evaluation_starts_all_controls(self):
        """Test that all controls start before any complete (parallel, not sequential)."""
        # Given: 3 slow controls
        controls = [
            make_control(1, "slow1", "test-slow", action="log", config_value="1"),
            make_control(2, "slow2", "test-slow", action="log", config_value="2"),
            make_control(3, "slow3", "test-slow", action="log", config_value="3"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        await engine.process(request)

        # Then: All should have started before any ended (parallel execution)
        # If sequential: start1, end1, start2, end2, start3, end3
        # If parallel: start1, start2, start3, end1, end2, end3 (order may vary)
        starts = [i for i, log in enumerate(_execution_log) if ":start" in log]
        ends = [i for i, log in enumerate(_execution_log) if ":end" in log]

        # All starts should come before all ends if truly parallel
        assert max(starts) < min(ends), (
            f"Expected parallel execution but got sequential. Log: {_execution_log}"
        )

    @pytest.mark.asyncio
    async def test_parallel_evaluation_faster_than_sequential(self):
        """Test that parallel execution is faster than sequential would be."""
        import time

        # Given: 3 slow controls (each takes ~50ms)
        controls = [
            make_control(1, "slow1", "test-slow", action="log", config_value="1"),
            make_control(2, "slow2", "test-slow", action="log", config_value="2"),
            make_control(3, "slow3", "test-slow", action="log", config_value="3"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        start = time.monotonic()
        await engine.process(request)
        elapsed = time.monotonic() - start

        # Then: Should complete in ~50ms (parallel), not ~150ms (sequential)
        # Allow some buffer for test overhead
        assert elapsed < 0.12, (
            f"Expected parallel execution (~50ms) but took {elapsed*1000:.0f}ms"
        )


# =============================================================================
# Test: Cancel on Deny
# =============================================================================


class TestCancelOnDeny:
    """Tests verifying cancellation when deny is found."""

    @pytest.mark.asyncio
    async def test_cancel_on_deny_cancels_blocking_tasks(self):
        """Test that blocking tasks are cancelled when another control denies."""
        # Given: A blocker (waits forever) and a denier (returns immediately)
        controls = [
            make_control(1, "blocker", "test-blocker", action="log", config_value="b"),
            make_control(2, "denier", "test-deny", action="deny", config_value="d"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Blocker should have started and been cancelled
        assert "blocker:b:start" in _execution_log, "Blocker should have started"
        assert "blocker:b:cancelled" in _execution_log, "Blocker should have been cancelled"
        assert "blocker:b:end" not in _execution_log, "Blocker should not have completed"

        # And: Denier should have completed
        assert "deny:d:start" in _execution_log
        assert "deny:d:end" in _execution_log

        # And: Result should be denied
        assert result.is_safe is False
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "denier"

    @pytest.mark.asyncio
    async def test_cancel_on_deny_with_multiple_blockers(self):
        """Test that multiple blocking tasks are all cancelled."""
        # Given: Multiple blockers and one denier
        controls = [
            make_control(1, "blocker1", "test-blocker", action="log", config_value="1"),
            make_control(2, "blocker2", "test-blocker", action="log", config_value="2"),
            make_control(3, "denier", "test-deny", action="deny", config_value="d"),
            make_control(4, "blocker3", "test-blocker", action="log", config_value="3"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: All blockers should have started (parallel) and been cancelled
        for i in ["1", "2", "3"]:
            assert f"blocker:{i}:start" in _execution_log, f"Blocker {i} should have started"
            assert f"blocker:{i}:cancelled" in _execution_log, f"Blocker {i} should be cancelled"

        # And: Result should be denied
        assert result.is_safe is False

    @pytest.mark.asyncio
    async def test_no_cancel_on_non_deny_match(self):
        """Test that 'log' action match doesn't cancel other tasks."""
        # Given: A slow task and a matcher with action=log (not deny)
        controls = [
            make_control(1, "slow", "test-slow", action="log", config_value="s"),
            make_control(2, "matcher", "test-deny", action="log", config_value="m"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Slow task should complete (not cancelled) because action was 'log'
        assert "slow:s:end" in _execution_log, "Slow task should complete for non-deny match"

        # And: Result should still be safe (log doesn't make it unsafe)
        assert result.is_safe is True
        assert result.matches is not None
        assert len(result.matches) == 1

    @pytest.mark.asyncio
    async def test_first_deny_wins(self):
        """Test that first deny is captured even with multiple deniers."""
        # Given: Multiple deny controls
        controls = [
            make_control(1, "deny1", "test-deny", action="deny", config_value="1"),
            make_control(2, "deny2", "test-deny", action="deny", config_value="2"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Result should be denied
        assert result.is_safe is False
        # At least one deny should be in matches
        assert result.matches is not None
        assert any(m.action == "deny" for m in result.matches)


# =============================================================================
# Test: Result Collection
# =============================================================================


class TestResultCollection:
    """Tests for correct result collection."""

    @pytest.mark.asyncio
    async def test_collect_all_completed_results(self):
        """Test that all completed results are collected."""
        # Given: Multiple quick controls
        controls = [
            make_control(1, "allow1", "test-allow", action="log", config_value="1"),
            make_control(2, "deny1", "test-deny", action="log", config_value="d"),
            make_control(3, "allow2", "test-allow", action="log", config_value="2"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Only matched controls should be in results
        assert result.matches is not None
        assert len(result.matches) == 1  # Only the deny matched
        assert result.matches[0].control_name == "deny1"

    @pytest.mark.asyncio
    async def test_no_matches_when_all_allow(self):
        """Test empty matches when no controls match."""
        # Given: All allow controls
        controls = [
            make_control(1, "allow1", "test-allow", action="deny", config_value="1"),
            make_control(2, "allow2", "test-allow", action="deny", config_value="2"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: No matches, is_safe=True
        assert result.is_safe is True
        assert result.matches is None


# =============================================================================
# Test: Error Handling (Fail-Closed for Deny, Error Field)
# =============================================================================


class ErrorEvaluator(Evaluator[SimpleConfig]):
    """Evaluator that always raises an exception."""

    metadata = EvaluatorMetadata(
        name="test-error",
        version="1.0.0",
        description="Always raises an error",
    )
    config_model = SimpleConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        _execution_log.append(f"error:{self.config.value}:start")
        raise RuntimeError(f"Intentional error from {self.config.value}")


class TimeoutConfig(BaseModel):
    """Config for timeout evaluator with custom timeout."""

    value: str = "default"
    timeout_ms: int = 100  # Very short timeout for testing


class TimeoutEvaluator(Evaluator[TimeoutConfig]):
    """Evaluator that sleeps longer than its timeout."""

    metadata = EvaluatorMetadata(
        name="test-timeout",
        version="1.0.0",
        description="Sleeps longer than timeout",
        timeout_ms=100,  # 100ms default
    )
    config_model = TimeoutConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        _execution_log.append(f"timeout:{self.config.value}:start")
        # Sleep for 5 seconds - way longer than the 100ms timeout
        await asyncio.sleep(5.0)
        _execution_log.append(f"timeout:{self.config.value}:end")
        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="Should never reach here",
        )


class TestErrorHandling:
    """Tests for error handling - fail-closed for deny controls, error field."""

    @pytest.fixture(autouse=True)
    def register_error_evaluator(self):
        """Register ErrorEvaluator for these tests."""
        try:
            register_evaluator(ErrorEvaluator)
        except ValueError:
            pass  # Already registered

    @pytest.mark.asyncio
    async def test_evaluator_error_fails_closed_for_deny(self):
        """Test that deny controls fail closed when they error.

        Given: A deny control with an evaluator that throws an exception
        When: The engine processes the request
        Then: The request is marked unsafe (fail-closed) and confidence is 0
        """
        # Given: A deny control with an error-throwing evaluator
        controls = [
            make_control(1, "error_control", "test-error", action="deny", config_value="err"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Should fail closed (is_safe=False) for deny controls
        assert result.is_safe is False
        # Confidence is 0 because no successful evaluations occurred
        assert result.confidence == 0.0
        # No matches because the error control didn't produce a match
        assert result.matches is None
        # Error should be captured
        assert result.errors is not None
        assert len(result.errors) == 1
        # The evaluator should have started
        assert "error:err:start" in _execution_log

    @pytest.mark.asyncio
    async def test_error_does_not_affect_other_controls(self):
        """Test that one control's error doesn't affect others.

        Given: Multiple controls, one (log action) throws an error
        When: The engine processes the request
        Then: Other controls still execute and their results are collected
        """
        # Given: A mix of error and working controls (error has log action)
        controls = [
            make_control(1, "allow1", "test-allow", action="log", config_value="a1"),
            make_control(2, "error_control", "test-error", action="log", config_value="err"),
            make_control(3, "deny1", "test-deny", action="log", config_value="d1"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Working controls should have executed
        assert "allow:a1:start" in _execution_log
        assert "allow:a1:end" in _execution_log
        assert "deny:d1:start" in _execution_log
        assert "deny:d1:end" in _execution_log

        # And: Should be safe (log action fails open)
        assert result.is_safe is True
        # Confidence is 2/3 (two successful, one errored)
        assert abs(result.confidence - 2/3) < 0.01

        # And: The deny control match should be captured
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "deny1"

    @pytest.mark.asyncio
    async def test_error_with_log_action_fails_open(self):
        """Test that errored control with log action fails open.

        Given: A control with action=log that throws an error
        When: The engine processes the request
        Then: The request is safe (fail-open for non-deny actions)
        """
        # Given: Error control with log action (non-deny)
        controls = [
            make_control(1, "error_log", "test-error", action="log", config_value="el"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Should be safe - log action fails open
        assert result.is_safe is True
        # But confidence is 0 (no successful evaluations)
        assert result.confidence == 0.0
        assert result.matches is None
        # Error should be captured
        assert result.errors is not None

    @pytest.mark.asyncio
    async def test_unexpected_condition_error_is_captured_as_control_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unexpected traversal failures should surface as normal control errors."""
        # Given: a deny control whose condition traversal raises unexpectedly
        controls = [
            make_control(1, "unexpected_error", "test-allow", action="deny", config_value="ok"),
        ]
        engine = ControlEngine(controls)

        async def raise_unexpected(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("unexpected traversal bug")

        monkeypatch.setattr(engine, "_evaluate_condition", raise_unexpected)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the control is reported as an error instead of being silently dropped
        assert result.is_safe is False
        assert result.confidence == 0.0
        assert result.matches is None
        assert result.errors is not None
        assert len(result.errors) == 1
        assert result.errors[0].control_name == "unexpected_error"
        assert result.errors[0].result.error is not None
        assert "unexpected traversal bug" in result.errors[0].result.error

    @pytest.mark.asyncio
    async def test_missing_evaluator_error_sets_error_field(self):
        """Test that missing evaluator error sets error field in result.

        Given: A deny control with an evaluator that doesn't exist
        When: The engine processes the request
        Then: The error field is set, is_safe=False (deny fails closed)
        """
        # Given: A deny control with non-existent evaluator
        controls = [
            make_control(
                1, "missing_evaluator", "nonexistent-evaluator", action="deny", config_value="m"
            ),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Should fail closed (deny control errored)
        assert result.is_safe is False
        assert result.confidence == 0.0
        assert result.matches is None

        # Error should be captured
        assert result.errors is not None
        assert len(result.errors) == 1
        assert result.errors[0].control_name == "missing_evaluator"
        assert result.errors[0].result.error is not None
        assert "nonexistent-evaluator" in result.errors[0].result.error.lower()

    @pytest.mark.asyncio
    async def test_errors_array_exposes_evaluator_failures(self):
        """Test that errors array exposes all evaluator failures.

        Given: Multiple controls, some throw errors, some succeed
        When: The engine processes the request
        Then: All errored evaluations are in the errors array, deny errors fail closed
        """
        # Given: Mix of working and errored controls (error1 is deny, error2 is log)
        controls = [
            make_control(1, "allow1", "test-allow", action="log", config_value="a1"),
            make_control(2, "error1", "test-error", action="deny", config_value="e1"),
            make_control(3, "deny1", "test-deny", action="warn", config_value="d1"),
            make_control(4, "error2", "test-error", action="log", config_value="e2"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: is_safe=False because deny control errored (fail closed)
        assert result.is_safe is False

        # Then: Confidence is 0 because deny control errored (can't be confident)
        assert result.confidence == 0.0

        # Then: Matches should contain only successful evaluations
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "deny1"
        assert result.matches[0].result.error is None

        # Then: Errors should contain all failed evaluations
        assert result.errors is not None
        assert len(result.errors) == 2
        error_names = {e.control_name for e in result.errors}
        assert error_names == {"error1", "error2"}

        # And: All errors should have the error field set
        for error_match in result.errors:
            assert error_match.result.error is not None
            assert "RuntimeError" in error_match.result.error

    @pytest.mark.asyncio
    async def test_errors_array_empty_when_no_errors(self):
        """Test that errors array is None when no errors occur.

        Given: Controls that all succeed
        When: The engine processes the request
        Then: The errors field is None
        """
        # Given: All working controls
        controls = [
            make_control(1, "allow1", "test-allow", action="log", config_value="a1"),
            make_control(2, "deny1", "test-deny", action="warn", config_value="d1"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: No errors
        assert result.errors is None

        # And: Matches should be present
        assert result.matches is not None
        assert len(result.matches) == 1


# =============================================================================
# Test: Confidence Calculation
# =============================================================================


class TestConfidenceCalculation:
    """Tests for confidence calculation with cancelled tasks."""

    @pytest.mark.asyncio
    async def test_confidence_is_full_on_deny_match(self):
        """Test that confidence is 1.0 when a deny match is found.

        Given: A deny control that matches and blockers that get cancelled
        When: The engine processes the request
        Then: Confidence is 1.0 (definitive deny decision)
        """
        # Given: 1 denier and 9 blockers (simulating cancelled tasks)
        controls = [
            make_control(1, "denier", "test-deny", action="deny", config_value="d"),
        ] + [
            make_control(i + 2, f"blocker{i}", "test-blocker", action="log", config_value=str(i))
            for i in range(9)
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Confidence should be 1.0 (definitive deny)
        assert result.is_safe is False
        assert result.confidence == 1.0
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "denier"

    @pytest.mark.asyncio
    async def test_confidence_excludes_cancelled_tasks(self):
        """Test that cancelled tasks don't count toward confidence denominator.

        Given: Controls where some complete and some are cancelled
        When: All evaluated controls succeed (no errors)
        Then: Confidence is 1.0 (based only on evaluated tasks)
        """
        # Given: 2 quick allow controls and 2 blockers, plus 1 deny
        # The deny will cancel the blockers, but allow controls complete
        controls = [
            make_control(1, "allow1", "test-allow", action="log", config_value="a1"),
            make_control(2, "allow2", "test-allow", action="log", config_value="a2"),
            make_control(3, "blocker1", "test-blocker", action="log", config_value="b1"),
            make_control(4, "blocker2", "test-blocker", action="log", config_value="b2"),
            make_control(5, "denier", "test-deny", action="deny", config_value="d"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Confidence is 1.0 because deny is definitive
        assert result.is_safe is False
        assert result.confidence == 1.0

        # Verify blockers were cancelled
        assert "blocker:b1:cancelled" in _execution_log or "blocker:b1:start" in _execution_log
        assert "blocker:b2:cancelled" in _execution_log or "blocker:b2:start" in _execution_log

    @pytest.mark.asyncio
    async def test_confidence_proportional_without_deny_match(self):
        """Test that confidence is proportional when no deny match occurs.

        Given: Controls with some errors but no deny match
        When: Some controls error but none match with deny
        Then: Confidence is successful/evaluated ratio
        """
        # Given: 2 successful log controls, 1 errored log control
        controls = [
            make_control(1, "allow1", "test-allow", action="log", config_value="a1"),
            make_control(2, "allow2", "test-allow", action="log", config_value="a2"),
            make_control(3, "error1", "test-error", action="log", config_value="e1"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Confidence is 2/3 (2 successful out of 3 evaluated)
        assert result.is_safe is True  # Log action, no deny match
        assert abs(result.confidence - 2/3) < 0.01

    @pytest.mark.asyncio
    async def test_confidence_zero_when_deny_errors_despite_other_successes(self):
        """Test that confidence is 0 when a deny control errors.

        Given: Multiple controls where one deny control errors but others succeed
        When: The deny control throws an exception
        Then: Confidence is 0 (can't trust safety assessment), is_safe=False
        """
        # Given: 3 successful controls + 1 deny that errors
        controls = [
            make_control(1, "allow1", "test-allow", action="log", config_value="a1"),
            make_control(2, "allow2", "test-allow", action="log", config_value="a2"),
            make_control(3, "allow3", "test-allow", action="log", config_value="a3"),
            make_control(4, "deny_error", "test-error", action="deny", config_value="de"),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: is_safe=False (fail closed) and confidence=0 (can't trust result)
        assert result.is_safe is False
        assert result.confidence == 0.0
        # Error should be captured
        assert result.errors is not None
        assert len(result.errors) == 1
        assert result.errors[0].control_name == "deny_error"


# =============================================================================
# Test: Timeout Enforcement
# =============================================================================


# =============================================================================
# Test: Selector Step Scoping and Optional Path
# =============================================================================


class PayloadEchoEvaluator(Evaluator[SimpleConfig]):
    """Evaluator that inspects full payload when path is omitted ("*")."""

    metadata = EvaluatorMetadata(
        name="test-payload-echo",
        version="1.0.0",
        description="Echo payload info",
    )
    config_model = SimpleConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        # If we received the full payload as JSON, it has dict keys for type/name
        if isinstance(data, dict):
            step_type = data.get("type")
            step_name = data.get("name")
            if step_type and step_name:
                _execution_log.append(f"payload_dict:{step_type}:{step_name}")
            else:
                _execution_log.append("payload_dict:<none>")
        else:
            step_type = getattr(data, "type", None)
            step_name = getattr(data, "name", None)
            if step_type and step_name:
                _execution_log.append(f"payload_step:{step_type}:{step_name}")
            else:
                _execution_log.append("payload_step:<none>")
        return EvaluatorResult(matched=False, confidence=1.0, message="ok")


class TestSelectorStepScoping:
    @pytest.fixture(autouse=True)
    def register_payload_evaluator(self):
        try:
            register_evaluator(PayloadEchoEvaluator)
        except ValueError:
            pass

    @pytest.mark.asyncio
    async def test_step_names_filters_tasks(self):
        # Given: two controls scoped to different steps
        controls = [
            make_control(
                1,
                "allow_copy",
                "test-allow",
                action="log",
                config_value="copy",
                step_types=["tool"],
                path="input",
                step_names=["copy_file"],
            ),
            make_control(
                2,
                "allow_aws",
                "test-allow",
                action="log",
                config_value="aws",
                step_types=["tool"],
                path="input",
                step_names=["aws_cli"],
            ),
        ]
        engine = ControlEngine(controls)
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="tool", name="copy_file", input={}, output=None),
            stage="pre",
        )
        await engine.process(request)
        # Then: only copy control ran
        log = "|".join(_execution_log)
        assert "allow:copy:start" in log and "allow:copy:end" in log
        assert "allow:aws:start" not in log and "allow:aws:end" not in log

    @pytest.mark.asyncio
    async def test_step_name_regex_filters_tasks(self):
        # Given: regex scoping for db_*
        controls = [
            make_control(
                1,
                "allow_db",
                "test-allow",
                action="log",
                config_value="db",
                step_types=["tool"],
                path="input",
                step_name_regex=r"^db_.*",
            ),
            make_control(
                2,
                "allow_web",
                "test-allow",
                action="log",
                config_value="web",
                step_types=["tool"],
                path="input",
                step_name_regex=r"^web_.*",
            ),
        ]
        engine = ControlEngine(controls)
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="tool", name="db_query", input={}, output=None),
            stage="pre",
        )
        await engine.process(request)
        log = "|".join(_execution_log)
        assert "allow:db:start" in log and "allow:db:end" in log
        assert "allow:web:start" not in log and "allow:web:end" not in log

    @pytest.mark.asyncio
    async def test_or_semantics_names_or_regex(self):
        # Given: both names and regex present; OR semantics
        controls = [
            make_control(
                1,
                "allow_mixed",
                "test-allow",
                action="log",
                config_value="mixed",
                step_types=["tool"],
                path="input",
                step_names=["build"],
                step_name_regex=r"^db_.*",
            ),
        ]
        engine = ControlEngine(controls)
        # Matches by regex despite name mismatch
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="tool", name="db_export", input={}, output=None),
            stage="pre",
        )
        await engine.process(request)
        log = "|".join(_execution_log)
        assert "allow:mixed:start" in log and "allow:mixed:end" in log

    @pytest.mark.asyncio
    async def test_path_optional_defaults_to_star(self):
        # Given: path omitted; evaluator should receive full payload
        controls = [
            make_control(
                1,
                "payload_echo",
                "test-payload-echo",
                action="log",
                config_value="p",
                step_types=["tool"],
                path=None,  # omit path to use "*"
                step_names=["copy_file"],
            )
        ]
        engine = ControlEngine(controls)
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="tool", name="copy_file", input={}, output=None),
            stage="pre",
        )
        await engine.process(request)
        assert "payload_dict:tool:copy_file" in _execution_log

    def test_invalid_step_name_regex_rejected(self):
        # ControlDefinition should reject invalid regex during validation
        with pytest.raises(Exception):
            ControlDefinition(
                description="bad regex",
                enabled=True,
                execution="server",
                scope={"step_types": ["tool"], "stages": ["pre"], "step_name_regex": "("},
                condition={
                    "selector": {"path": "input"},
                    "evaluator": EvaluatorSpec(name="test-allow", config={"value": "x"}),
                },
                action={"decision": "log"},
            )


class TestTimeoutEnforcement:
    """Tests for per-evaluator timeout enforcement."""

    @pytest.fixture(autouse=True)
    def register_timeout_evaluator(self):
        """Register TimeoutEvaluator for these tests."""
        try:
            register_evaluator(TimeoutEvaluator)
        except ValueError:
            pass  # Already registered

    @pytest.mark.asyncio
    async def test_evaluator_timeout_is_enforced(self):
        """Test that evaluators are killed after their timeout expires.

        Given: A control with an evaluator that sleeps longer than its timeout
        When: The engine processes the request
        Then: The evaluation times out and error is captured
        """
        import time

        # Given: A control with a timeout evaluator (100ms timeout, 5s sleep)
        controls = [
            MockControlWithIdentity(
                id=1,
                name="timeout_control",
                control=ControlDefinition(
                    description="Test timeout",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "selector": {"path": "input"},
                        "evaluator": EvaluatorSpec(
                            name="test-timeout",
                            config={"value": "t1", "timeout_ms": 100},
                        ),
                    },
                    action={"decision": "deny"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        start = time.monotonic()
        result = await engine.process(request)
        elapsed = time.monotonic() - start

        # Then: Should complete quickly (timeout, not full 5s sleep)
        assert elapsed < 1.0, f"Expected timeout ~0.1s but took {elapsed:.2f}s"

        # And: Evaluator should have started
        assert "timeout:t1:start" in _execution_log
        # But not finished (was killed)
        assert "timeout:t1:end" not in _execution_log

        # And: Error should be captured with timeout message
        assert result.errors is not None
        assert len(result.errors) == 1
        assert "TimeoutError" in result.errors[0].result.error
        assert "timeout" in result.errors[0].result.error.lower()

        # And: Should fail closed for deny control
        assert result.is_safe is False
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_timeout_does_not_affect_fast_evaluators(self):
        """Test that fast evaluators complete normally without timeout issues.

        Given: A mix of fast and slow (timing out) controls
        When: The engine processes the request
        Then: Fast controls complete successfully, slow ones timeout
        """
        # Given: One fast allow and one slow timeout
        controls = [
            make_control(1, "fast", "test-allow", action="log", config_value="f1"),
            MockControlWithIdentity(
                id=2,
                name="slow_timeout",
                control=ControlDefinition(
                    description="Test timeout",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "selector": {"path": "input"},
                        "evaluator": EvaluatorSpec(
                            name="test-timeout",
                            config={"value": "slow", "timeout_ms": 100},
                        ),
                    },
                    action={"decision": "log"},  # Log, not deny - so fails open
                ),
            ),
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: Fast evaluator should have completed normally
        assert "allow:f1:start" in _execution_log
        assert "allow:f1:end" in _execution_log

        # And: Slow evaluator should have timed out
        assert "timeout:slow:start" in _execution_log
        assert "timeout:slow:end" not in _execution_log

        # And: Result should have error for slow, success for fast
        assert result.errors is not None
        assert len(result.errors) == 1
        assert result.errors[0].control_name == "slow_timeout"

        # And: Should be safe (log action fails open)
        assert result.is_safe is True
        # Confidence is 0.5 (1 success, 1 error out of 2)
        assert result.confidence == 0.5


# =============================================================================
# Test: Concurrency Limit
# =============================================================================


class TestConcurrencyLimit:
    """Tests for semaphore-based concurrency limiting."""

    @pytest.mark.asyncio
    async def test_concurrency_limited_to_max(self, monkeypatch: pytest.MonkeyPatch):
        """Test that concurrent evaluations are limited by semaphore.

        Given: More controls than MAX_CONCURRENT_EVALUATIONS, each tracking concurrency
        When: Processing all controls
        Then: At most MAX_CONCURRENT_EVALUATIONS run simultaneously
        """
        import agent_control_engine.core as core_module

        # Set a low concurrency limit for testing
        monkeypatch.setattr(core_module, "MAX_CONCURRENT_EVALUATIONS", 2)

        # Track max concurrent executions
        _concurrent_count = 0
        _max_concurrent = 0
        _lock = asyncio.Lock()

        class ConcurrencyTracker(Evaluator[SimpleConfig]):
            """Evaluator that tracks concurrent execution count."""

            metadata = EvaluatorMetadata(
                name="test-concurrency",
                version="1.0.0",
                description="Tracks concurrency",
            )
            config_model = SimpleConfig

            async def evaluate(self, data: Any) -> EvaluatorResult:
                nonlocal _concurrent_count, _max_concurrent
                async with _lock:
                    _concurrent_count += 1
                    _max_concurrent = max(_max_concurrent, _concurrent_count)
                await asyncio.sleep(0.05)  # Small delay to overlap
                async with _lock:
                    _concurrent_count -= 1
                return EvaluatorResult(matched=False, confidence=1.0, message="ok")

        try:
            register_evaluator(ConcurrencyTracker)
        except ValueError:
            pass

        # Given: 6 controls (more than the limit of 2)
        controls = [
            make_control(i, f"ctrl{i}", "test-concurrency", action="log", config_value=str(i))
            for i in range(6)
        ]
        engine = ControlEngine(controls)

        # When: Processing
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        await engine.process(request)

        # Then: Max concurrent should not exceed the limit
        assert _max_concurrent <= 2, f"Expected max 2 concurrent, got {_max_concurrent}"


# =============================================================================
# Test: Recursive Condition Trees
# =============================================================================


class TestConditionTrees:
    """Tests for recursive condition evaluation and trace metadata."""

    @pytest.fixture(autouse=True)
    def register_error_evaluator(self):
        """Register ErrorEvaluator for these tests."""
        try:
            register_evaluator(ErrorEvaluator)
        except ValueError:
            pass

    @pytest.mark.asyncio
    async def test_or_short_circuit_records_skipped_trace(self):
        """A matching OR child should short-circuit later children and mark them skipped."""
        # Given: an OR tree whose first child matches
        controls = [
            MockControlWithIdentity(
                id=1,
                name="or_short_circuit",
                control=ControlDefinition(
                    description="Short-circuit OR",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "or": [
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-deny", "config": {"value": "match"}},
                            },
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-slow", "config": {"value": "skip"}},
                            },
                        ]
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: later children are short-circuited and marked skipped in the trace
        assert result.matches is not None
        assert len(result.matches) == 1
        assert "slow:skip:start" not in _execution_log

        trace = result.matches[0].result.metadata["condition_trace"]
        assert trace["type"] == "or"
        assert trace["matched"] is True
        assert trace["short_circuit_reason"] == "or_matched"
        assert trace["children"][0]["evaluated"] is True
        assert trace["children"][0]["matched"] is True
        assert trace["children"][1]["evaluated"] is False
        assert trace["children"][1]["matched"] is None
        assert trace["children"][1]["short_circuit_reason"] == "or_matched"

    @pytest.mark.asyncio
    async def test_composite_results_preserve_decisive_child_metadata(self):
        """Composite results should retain structured metadata from the decisive child."""
        # Given: an OR tree where the second child decides the result
        controls = [
            MockControlWithIdentity(
                id=1,
                name="or_metadata",
                control=ControlDefinition(
                    description="Preserve decisive metadata",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "or": [
                            {
                                "selector": {"path": "input"},
                                "evaluator": {
                                    "name": "test-metadata",
                                    "config": {"value": "miss-left"},
                                },
                            },
                            {
                                "selector": {"path": "output"},
                                "evaluator": {
                                    "name": "test-metadata",
                                    "config": {"value": "match-right"},
                                },
                            },
                            {
                                "selector": {"path": "name"},
                                "evaluator": {
                                    "name": "test-slow",
                                    "config": {"value": "skip-tail"},
                                },
                            },
                        ]
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output="chosen"),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the composite retains the metadata from the matching child
        assert result.matches is not None
        metadata = result.matches[0].result.metadata
        assert metadata is not None
        assert metadata["source"] == "match-right"
        assert metadata["selected_data"] == "chosen"
        assert metadata["condition_trace"]["type"] == "or"
        assert "slow:skip-tail:start" not in _execution_log

    @pytest.mark.asyncio
    async def test_and_condition_all_children_match_records_full_trace(self):
        """A fully-evaluated AND tree should record every child and produce a match."""
        # Given: an AND tree where every leaf evaluator matches
        controls = [
            MockControlWithIdentity(
                id=1,
                name="and_all_match",
                control=ControlDefinition(
                    description="All AND children match",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "and": [
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-deny", "config": {"value": "first"}},
                            },
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-deny", "config": {"value": "second"}},
                            },
                        ]
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the control matches and every child appears as evaluated in the trace
        assert result.matches is not None
        assert len(result.matches) == 1
        trace = result.matches[0].result.metadata["condition_trace"]
        assert trace["type"] == "and"
        assert trace["matched"] is True
        assert "short_circuit_reason" not in trace
        assert len(trace["children"]) == 2
        assert all(child["evaluated"] is True for child in trace["children"])
        assert "deny:first:end" in _execution_log
        assert "deny:second:end" in _execution_log

    @pytest.mark.asyncio
    async def test_not_condition_inverts_child_result(self):
        """NOT should invert the child match result while preserving trace structure."""
        # Given: a NOT tree whose child returns non-match
        controls = [
            MockControlWithIdentity(
                id=1,
                name="not_condition",
                control=ControlDefinition(
                    description="Invert non-match",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "not": {
                            "selector": {"path": "input"},
                            "evaluator": {"name": "test-allow", "config": {"value": "child"}},
                        }
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the NOT node inverts the child result and preserves trace structure
        assert result.matches is not None
        trace = result.matches[0].result.metadata["condition_trace"]
        assert trace["type"] == "not"
        assert trace["matched"] is True
        assert len(trace["children"]) == 1
        assert trace["children"][0]["type"] == "leaf"
        assert trace["children"][0]["matched"] is False

    @pytest.mark.asyncio
    async def test_not_condition_propagates_child_error_trace(self):
        """NOT should surface child evaluator failures as composite errors."""
        # Given: a NOT tree whose child evaluator raises an error
        controls = [
            MockControlWithIdentity(
                id=1,
                name="not_error",
                control=ControlDefinition(
                    description="Invert errored child",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "not": {
                            "selector": {"path": "input"},
                            "evaluator": {"name": "test-error", "config": {"value": "boom"}},
                        }
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the composite returns an error result and preserves the child trace
        assert result.errors is not None
        assert len(result.errors) == 1
        trace = result.errors[0].result.metadata["condition_trace"]
        assert trace["type"] == "not"
        assert trace["matched"] is None
        assert len(trace["children"]) == 1
        assert trace["children"][0]["evaluated"] is True
        assert "Intentional error from boom" in trace["children"][0]["error"]

    @pytest.mark.asyncio
    async def test_or_condition_all_children_non_match_records_full_trace(self):
        """A fully-evaluated OR tree should record every child and produce a non-match."""
        # Given: an OR tree where every leaf evaluator returns non-match
        controls = [
            MockControlWithIdentity(
                id=1,
                name="or_all_non_match",
                control=ControlDefinition(
                    description="All OR children miss",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "or": [
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-allow", "config": {"value": "first"}},
                            },
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-allow", "config": {"value": "second"}},
                            },
                        ]
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the control is recorded as a non-match and every child is evaluated
        assert result.non_matches is not None
        assert len(result.non_matches) == 1
        trace = result.non_matches[0].result.metadata["condition_trace"]
        assert trace["type"] == "or"
        assert trace["matched"] is False
        assert "short_circuit_reason" not in trace
        assert len(trace["children"]) == 2
        assert all(child["evaluated"] is True for child in trace["children"])
        assert "allow:first:end" in _execution_log
        assert "allow:second:end" in _execution_log

    @pytest.mark.asyncio
    async def test_and_error_records_skipped_children_in_trace(self):
        """Errors in composite conditions should preserve trace context for skipped branches."""
        # Given: an AND tree whose first child evaluator errors
        controls = [
            MockControlWithIdentity(
                id=1,
                name="and_error",
                control=ControlDefinition(
                    description="Error in AND",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "and": [
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-error", "config": {"value": "boom"}},
                            },
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-slow", "config": {"value": "skip"}},
                            },
                        ]
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the trace preserves the erroring child and marks remaining children skipped
        assert result.errors is not None
        assert len(result.errors) == 1
        assert "slow:skip:start" not in _execution_log

        trace = result.errors[0].result.metadata["condition_trace"]
        assert trace["type"] == "and"
        assert trace["matched"] is None
        assert trace["short_circuit_reason"] == "error"
        assert result.errors[0].result.message.startswith(
            "Condition evaluation aborted due to a child evaluator error:"
        )
        assert trace["children"][0]["evaluated"] is True
        assert "Intentional error from boom" in trace["children"][0]["error"]
        assert trace["children"][1]["evaluated"] is False
        assert trace["children"][1]["short_circuit_reason"] == "error"

    @pytest.mark.asyncio
    async def test_or_error_records_skipped_children_in_trace(self):
        """OR error traces should be marked indeterminate, not as a definitive non-match."""
        # Given: an OR tree whose first child evaluator errors
        controls = [
            MockControlWithIdentity(
                id=1,
                name="or_error",
                control=ControlDefinition(
                    description="Error in OR",
                    enabled=True,
                    execution="server",
                    scope={"step_types": ["llm"], "stages": ["pre"]},
                    condition={
                        "or": [
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-error", "config": {"value": "boom"}},
                            },
                            {
                                "selector": {"path": "input"},
                                "evaluator": {"name": "test-allow", "config": {"value": "skip"}},
                            },
                        ]
                    },
                    action={"decision": "log"},
                ),
            )
        ]
        engine = ControlEngine(controls)

        # When: processing the request
        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Then: the trace preserves the erroring child and marks remaining children skipped
        assert result.errors is not None
        assert len(result.errors) == 1
        assert "allow:skip:end" not in _execution_log

        trace = result.errors[0].result.metadata["condition_trace"]
        assert trace["type"] == "or"
        assert trace["matched"] is None
        assert trace["short_circuit_reason"] == "error"
        assert result.errors[0].result.message.startswith(
            "Condition evaluation aborted due to a child evaluator error:"
        )
        assert trace["children"][0]["evaluated"] is True
        assert "Intentional error from boom" in trace["children"][0]["error"]
        assert trace["children"][1]["evaluated"] is False
        assert trace["children"][1]["short_circuit_reason"] == "error"


# =============================================================================
# Test: Context Filtering (local vs server)
# =============================================================================


def make_control_with_execution(
    control_id: int,
    name: str,
    evaluator: str,
    action: str = "deny",
    config_value: str = "default",
    *,
    execution: str = "server",
    step_types: list[str] | None = None,
    stages: list[str] | None = None,
    step_names: list[str] | None = None,
    step_name_regex: str | None = None,
    path: str = "input",
) -> MockControlWithIdentity:
    """Create a mock control with the execution field set."""
    if step_types is None:
        step_types = ["llm"]
    if stages is None:
        stages = ["pre"]
    scope: dict[str, Any] = {"step_types": step_types, "stages": stages}
    if step_names is not None:
        scope["step_names"] = step_names
    if step_name_regex is not None:
        scope["step_name_regex"] = step_name_regex

    return MockControlWithIdentity(
        id=control_id,
        name=name,
        control=ControlDefinition(
            description=f"Test control {name}",
            enabled=True,
            execution=execution,
            scope=scope,
            condition={
                "selector": {"path": path},
                "evaluator": EvaluatorSpec(
                    name=evaluator,
                    config={"value": config_value},
                ),
            },
            action={"decision": action},
        ),
    )


class TestContextFiltering:
    """Tests for context-based filtering (execution vs server)."""

    @pytest.mark.asyncio
    async def test_server_context_only_runs_server_controls(self):
        """Test that server context only runs execution='server' controls.

        Given: Controls with execution='sdk' and execution='server'
        When: Engine runs with context='server'
        Then: Only execution='server' controls are executed
        """
        controls = [
            make_control_with_execution(
                1, "local_ctrl", "test-allow", action="log", config_value="loc", execution="sdk"
            ),
            make_control_with_execution(
                2, "server_ctrl", "test-allow", action="log", config_value="srv", execution="server"
            ),
        ]
        engine = ControlEngine(controls, context="server")

        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        await engine.process(request)

        # Only server_ctrl should have run
        log = "|".join(_execution_log)
        assert "allow:srv:start" in log and "allow:srv:end" in log
        assert "allow:loc:start" not in log and "allow:loc:end" not in log

    @pytest.mark.asyncio
    async def test_sdk_context_only_runs_sdk_controls(self):
        """Test that SDK context only runs execution='sdk' controls.

        Given: Controls with execution='sdk' and execution='server'
        When: Engine runs with context='sdk'
        Then: Only execution='sdk' controls are executed
        """
        controls = [
            make_control_with_execution(
                1, "local_ctrl", "test-allow", action="log", config_value="loc", execution="sdk"
            ),
            make_control_with_execution(
                2, "server_ctrl", "test-allow", action="log", config_value="srv", execution="server"
            ),
        ]
        engine = ControlEngine(controls, context="sdk")

        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        await engine.process(request)

        # Only local_ctrl should have run
        log = "|".join(_execution_log)
        assert "allow:loc:start" in log and "allow:loc:end" in log
        assert "allow:srv:start" not in log and "allow:srv:end" not in log

    @pytest.mark.asyncio
    async def test_default_context_is_server(self):
        """Test that default context is 'server'.

        Given: Controls with execution='sdk' and execution='server'
        When: Engine runs with default context (no context param)
        Then: Only execution='server' controls are executed
        """
        controls = [
            make_control_with_execution(
                1, "local_ctrl", "test-allow", action="log", config_value="loc", execution="sdk"
            ),
            make_control_with_execution(
                2, "server_ctrl", "test-allow", action="log", config_value="srv", execution="server"
            ),
        ]
        engine = ControlEngine(controls)  # No context param

        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        await engine.process(request)

        # Only server_ctrl should have run (default context is 'server')
        log = "|".join(_execution_log)
        assert "allow:srv:start" in log and "allow:srv:end" in log
        assert "allow:loc:start" not in log and "allow:loc:end" not in log

    @pytest.mark.asyncio
    async def test_sdk_context_empty_when_no_local_controls(self):
        """Test that SDK context returns early when no local controls exist.

        Given: Controls that are all execution='server'
        When: Engine runs with context='sdk'
        Then: No controls are executed, result is safe with full confidence
        """
        controls = [
            make_control_with_execution(
                1, "server1", "test-deny", action="deny", config_value="s1", execution="server"
            ),
            make_control_with_execution(
                2, "server2", "test-deny", action="deny", config_value="s2", execution="server"
            ),
        ]
        engine = ControlEngine(controls, context="sdk")

        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # No controls should run
        assert len(_execution_log) == 0
        # Result should be safe (no applicable controls)
        assert result.is_safe is True
        assert result.confidence == 1.0
        assert result.matches is None

    @pytest.mark.asyncio
    async def test_server_context_empty_when_all_local_controls(self):
        """Test that server context returns early when all controls are local.

        Given: Controls that are all execution='sdk'
        When: Engine runs with context='server'
        Then: No controls are executed, result is safe with full confidence
        """
        controls = [
            make_control_with_execution(
                1, "local1", "test-deny", action="deny", config_value="l1", execution="sdk"
            ),
            make_control_with_execution(
                2, "local2", "test-deny", action="deny", config_value="l2", execution="sdk"
            ),
        ]
        engine = ControlEngine(controls, context="server")

        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # No controls should run
        assert len(_execution_log) == 0
        # Result should be safe (no applicable controls)
        assert result.is_safe is True
        assert result.confidence == 1.0
        assert result.matches is None

    @pytest.mark.asyncio
    async def test_sdk_deny_works_in_sdk_context(self):
        """Test that execution='sdk' deny controls work correctly in SDK context.

        Given: A deny control that runs in the SDK
        When: Engine runs with context='sdk'
        Then: The deny is detected and is_safe=False
        """
        controls = [
            make_control_with_execution(
                1, "local_deny", "test-deny", action="deny", config_value="ld", execution="sdk"
            ),
        ]
        engine = ControlEngine(controls, context="sdk")

        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="llm", name="test-step", input="test", output=None),
            stage="pre",
        )
        result = await engine.process(request)

        # Deny should be detected
        assert "deny:ld:start" in _execution_log
        assert "deny:ld:end" in _execution_log
        assert result.is_safe is False
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "local_deny"

    @pytest.mark.asyncio
    async def test_context_filtering_combined_with_step_scoping(self):
        """Test that context filtering works together with step name scoping.

        Given: Controls with execution='sdk' and step_names scoping
        When: Engine runs with context='sdk' and a matching tool step
        Then: Only matching SDK controls for that step are executed
        """
        controls = [
            make_control_with_execution(
                1, "local_copy", "test-allow",
                action="log",
                config_value="lc",
                execution="sdk",
                step_types=["tool"],
                step_names=["copy_file"],
            ),
            make_control_with_execution(
                2, "server_copy", "test-allow",
                action="log",
                config_value="sc",
                execution="server",
                step_types=["tool"],
                step_names=["copy_file"],
            ),
        ]

        engine = ControlEngine(controls, context="sdk")

        request = EvaluationRequest(
            agent_name="00000000-0000-0000-0000-000000000001",
            step=Step(type="tool", name="copy_file", input={}, output=None),
            stage="pre",
        )
        await engine.process(request)

        # Only local_copy should run (sdk context + matching step)
        log = "|".join(_execution_log)
        assert "allow:lc:start" in log and "allow:lc:end" in log
        assert "allow:sc:start" not in log and "allow:sc:end" not in log


# =============================================================================
# Test: Regex Caching
# =============================================================================


class TestRegexCaching:
    """Tests for regex pattern caching."""

    def test_compile_regex_returns_pattern(self):
        """Test that _compile_regex returns a valid pattern."""
        pattern = _compile_regex(r"test.*pattern")
        assert pattern is not None
        assert pattern.search("test_foo_pattern") is not None
        assert pattern.search("no match") is None

    def test_compile_regex_caches_same_pattern(self):
        """Test that _compile_regex caches repeated patterns."""
        # Clear cache first
        _compile_regex.cache_clear()

        pattern1 = _compile_regex(r"cached_pattern")
        pattern2 = _compile_regex(r"cached_pattern")

        # Should be same object (cached)
        assert pattern1 is pattern2

        # Check cache info
        info = _compile_regex.cache_info()
        assert info.hits == 1
        assert info.misses == 1

    def test_compile_regex_different_patterns_cached_separately(self):
        """Test that different patterns are cached separately."""
        _compile_regex.cache_clear()

        pattern1 = _compile_regex(r"pattern_one")
        pattern2 = _compile_regex(r"pattern_two")

        # Should be different objects
        assert pattern1 is not pattern2

        # Both should be misses
        info = _compile_regex.cache_info()
        assert info.hits == 0
        assert info.misses == 2

# =============================================================================
# Test: Steer Error Handling
# =============================================================================


class TestSteerErrorHandling:
    """Tests for steer control error handling (lines 299, 340-344)."""

    @pytest.mark.asyncio
    async def test_steer_control_error_non_blocking(self):
        """Test that steer control errors don't block execution (unlike deny errors).

        Given: A steer control with an evaluator that errors
        When: Engine processes the request
        Then: Result is still safe (steer errors are non-blocking)
              Error is logged for observability
        Coverage: Lines 299 (steer_errored = True), 340-344 (logging)
        """
        reset_test_state()
        register_evaluator(ErrorEvaluator)

        controls = [
            make_control(
                1,
                "steer-with-error",
                evaluator="test-error",
                config_value="steer",
                action="steer",
                steering_context=SteeringContext(message="Steering guidance"),
            ),
        ]

        engine = ControlEngine(controls)
        request = EvaluationRequest(
            agent_name="test-agent",
            stage="pre",
            step=Step(type="llm", name="test-step", input="test", output=None),
        )

        # Capture logs to verify warning is logged
        import logging
        from io import StringIO

        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("agent_control_engine.core")
        logger.addHandler(handler)

        try:
            result = await engine.process(request)

            # Steer errors are NON-BLOCKING - result should still be safe
            assert result.is_safe is True

            # Error should be captured in errors list
            assert result.errors is not None
            assert len(result.errors) == 1
            assert result.errors[0].control_name == "steer-with-error"
            assert result.errors[0].action == "steer"
            assert result.errors[0].result.error is not None

            # Verify warning was logged (lines 340-344)
            log_output = log_capture.getvalue()
            assert "Steer control evaluation failed (non-blocking)" in log_output
            assert "steer-with-error" in log_output

        finally:
            logger.removeHandler(handler)

    @pytest.mark.asyncio
    async def test_deny_control_error_blocks(self):
        """Test that deny control errors DO block execution (fail closed).

        Given: A deny control with an evaluator that errors
        When: Engine processes the request
        Then: Result is unsafe (deny errors fail closed)
        """
        reset_test_state()
        register_evaluator(ErrorEvaluator)

        controls = [
            make_control(
                1,
                "deny-with-error",
                evaluator="test-error",
                config_value="deny",
                action="deny",
            ),
        ]

        engine = ControlEngine(controls)
        request = EvaluationRequest(
            agent_name="test-agent",
            stage="pre",
            step=Step(type="llm", name="test-step", input="test", output=None),
        )

        result = await engine.process(request)

        # Deny errors BLOCK - result should be unsafe (fail closed)
        assert result.is_safe is False

        # Error should be captured
        assert result.errors is not None
        assert len(result.errors) == 1
        assert result.errors[0].control_name == "deny-with-error"

    @pytest.mark.asyncio
    async def test_mixed_deny_and_steer_errors(self):
        """Test that both deny and steer errors are handled correctly together.

        Given: One deny control that errors and one steer control that errors
        When: Engine processes the request
        Then: Result is unsafe (deny error fails closed)
              Both errors are captured
              Steer error warning is logged
        Coverage: Lines 299, 340-344
        """
        reset_test_state()
        register_evaluator(ErrorEvaluator)

        controls = [
            make_control(
                1,
                "deny-error",
                evaluator="test-error",
                config_value="deny",
                action="deny",
            ),
            make_control(
                2,
                "steer-error",
                evaluator="test-error",
                config_value="steer",
                action="steer",
                steering_context=SteeringContext(message="Steer guidance"),
            ),
        ]

        engine = ControlEngine(controls)
        request = EvaluationRequest(
            agent_name="test-agent",
            stage="pre",
            step=Step(type="llm", name="test-step", input="test", output=None),
        )

        # Capture logs
        import logging
        from io import StringIO

        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("agent_control_engine.core")
        logger.addHandler(handler)

        try:
            result = await engine.process(request)

            # Deny error fails closed
            assert result.is_safe is False

            # Both errors captured
            assert result.errors is not None
            assert len(result.errors) == 2
            error_names = {e.control_name for e in result.errors}
            assert error_names == {"deny-error", "steer-error"}

            # Steer error warning logged (lines 340-344)
            log_output = log_capture.getvalue()
            assert "Steer control evaluation failed (non-blocking)" in log_output
            assert "steer-error" in log_output

        finally:
            logger.removeHandler(handler)


# =============================================================================
# Test: Invalid Regex Handling
# =============================================================================


class TestInvalidRegexHandling:
    """Tests for invalid step_name_regex error handling (line 139)."""

    @pytest.mark.asyncio
    async def test_invalid_step_name_regex_captured_in_selector_errors(self):
        """Test that invalid step_name_regex is captured in selector_errors.

        Given: A control with an invalid step_name_regex pattern
        When: Engine gets applicable controls with selector_errors list
        Then: The invalid regex error is added to selector_errors
              Control is skipped
        Coverage: Line 139 (continue after regex error)
        """

        @dataclass
        class MockControl:
            id: int
            name: str
            control: ControlDefinition

        # Create ControlDefinition with model_validate to bypass validation
        control_data = {
            "description": "Control with invalid regex",
            "enabled": True,
            "execution": "server",
            "scope": {
                "stages": ["pre"],
                "step_types": ["llm"],
                "step_name_regex": "[invalid(regex",  # Invalid regex pattern
            },
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {
                    "name": "test-allow",
                    "config": {"value": "test"},
                },
            },
            "action": {"decision": "deny"},
        }

        # Use model_validate with context to allow invalid regex
        control_def = ControlDefinition.model_validate(
            control_data,
            context={"allow_invalid_step_name_regex": True}
        )

        controls = [
            MockControl(
                id=1,
                name="invalid-regex-control",
                control=control_def,
            ),
        ]

        engine = ControlEngine(controls)
        request = EvaluationRequest(
            agent_name="test-agent",
            stage="pre",
            step=Step(
                type="llm",
                name="matching-step-name",
                input="test input",
                output=None,
            ),
        )

        selector_errors = []
        applicable = engine.get_applicable_controls(request, selector_errors=selector_errors)

        # Control should be skipped (not in applicable list)
        assert len(applicable) == 0

        # Error should be captured in selector_errors (line 139 coverage)
        assert len(selector_errors) == 1
        assert selector_errors[0].control_name == "invalid-regex-control"
        assert selector_errors[0].result.error is not None
        assert "Invalid step_name_regex" in selector_errors[0].result.error
        assert "[invalid(regex" in selector_errors[0].result.message
