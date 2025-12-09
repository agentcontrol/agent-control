"""Tests for ControlEngine parallel evaluation and cancel-on-deny.

These tests verify:
1. Controls are evaluated in parallel (not sequentially)
2. On first deny, remaining controls are cancelled
3. Results are collected correctly from completed evaluations
"""

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agent_control_models import (
    ControlDefinition,
    EvaluationRequest,
    EvaluatorConfig,
    EvaluatorResult,
    LlmCall,
    PluginEvaluator,
    PluginMetadata,
    register_plugin,
)
from agent_control_engine.core import ControlEngine
from agent_control_engine.evaluators import clear_evaluator_cache


# =============================================================================
# Test Fixtures and Helpers
# =============================================================================


class SimpleConfig(BaseModel):
    """Simple config for test plugins."""

    value: str = "default"


# Shared state for coordination between test plugins
_execution_log: list[str] = []
_blocker_event: asyncio.Event | None = None


def reset_test_state() -> None:
    """Reset shared test state."""
    global _execution_log, _blocker_event
    _execution_log = []
    _blocker_event = asyncio.Event()


class AllowPlugin(PluginEvaluator[SimpleConfig]):
    """Plugin that always allows (matched=False)."""

    metadata = PluginMetadata(
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


class DenyPlugin(PluginEvaluator[SimpleConfig]):
    """Plugin that always denies (matched=True)."""

    metadata = PluginMetadata(
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


class BlockerPlugin(PluginEvaluator[SimpleConfig]):
    """Plugin that blocks until cancelled or event is set.

    Used to test cancellation behavior.
    """

    metadata = PluginMetadata(
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


class SlowPlugin(PluginEvaluator[SimpleConfig]):
    """Plugin that sleeps briefly before returning."""

    metadata = PluginMetadata(
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


@dataclass
class MockControlWithIdentity:
    """Mock control for testing."""

    id: int
    name: str
    control: ControlDefinition


@pytest.fixture(autouse=True)
def setup_test_plugins():
    """Register test plugins and reset state before each test."""
    reset_test_state()
    clear_evaluator_cache()

    # Register plugins (may already be registered)
    for plugin_cls in [AllowPlugin, DenyPlugin, BlockerPlugin, SlowPlugin]:
        try:
            register_plugin(plugin_cls)
        except ValueError:
            pass  # Already registered

    yield

    reset_test_state()
    clear_evaluator_cache()


def make_control(
    control_id: int,
    name: str,
    plugin: str,
    action: str = "deny",
    config_value: str = "default",
) -> MockControlWithIdentity:
    """Create a mock control for testing."""
    return MockControlWithIdentity(
        id=control_id,
        name=name,
        control=ControlDefinition(
            description=f"Test control {name}",
            enabled=True,
            applies_to="llm_call",
            check_stage="pre",
            selector={"path": "input"},
            evaluator=EvaluatorConfig(
                plugin=plugin,
                config={"value": config_value},
            ),
            action={"decision": action},
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
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
            agent_uuid="00000000-0000-0000-0000-000000000001",
            payload=LlmCall(input="test", output=None),
            check_stage="pre",
        )
        result = await engine.process(request)

        # Then: No matches, is_safe=True
        assert result.is_safe is True
        assert result.matches is None
