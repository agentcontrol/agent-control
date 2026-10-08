"""Public engine contract tests for per-control execution durations."""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal
from unittest.mock import AsyncMock, Mock

import pytest
from agent_control_engine.core import ControlEngine
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import ControlDefinition, EvaluationRequest, EvaluatorResult, Step
from pydantic import BaseModel


class DurationConfig(BaseModel):
    matched: bool = False
    raises_error: bool = False
    blocks: bool = False


class DurationEvaluator(Evaluator[DurationConfig]):
    metadata = EvaluatorMetadata(
        name="test-duration",
        version="1.0.0",
        description="Returns a configured outcome or waits for cancellation",
    )
    config_model = DurationConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        # Yield once so concurrent controls all start before one completes.
        await asyncio.sleep(0)
        if self.config.blocks:
            await asyncio.Event().wait()
        if self.config.raises_error:
            raise RuntimeError("evaluation failed")
        return EvaluatorResult(matched=self.config.matched, confidence=1.0)


@dataclass
class DurationControl:
    id: int
    name: str
    control: ControlDefinition


@pytest.fixture(autouse=True)
def register_duration_evaluator() -> None:
    register_evaluator(DurationEvaluator)


@pytest.fixture
def evaluation_request() -> EvaluationRequest:
    return EvaluationRequest(
        agent_name="duration-test-agent",
        step=Step(type="llm", name="test-step", input="test", output=None),
        stage="pre",
    )


def make_control(
    control_id: int = 1,
    *,
    context: Literal["server", "sdk"] = "server",
    matched: bool = False,
    raises_error: bool = False,
    blocks: bool = False,
    decision: Literal["observe", "deny"] = "observe",
) -> DurationControl:
    return DurationControl(
        id=control_id,
        name=f"duration-control-{control_id}",
        control=ControlDefinition(
            description="Duration test control",
            enabled=True,
            execution=context,
            scope={"stages": ["pre"], "step_types": ["llm"]},
            condition={
                "selector": {"path": "input"},
                "evaluator": {
                    "name": "test-duration",
                    "config": {
                        "matched": matched,
                        "raises_error": raises_error,
                        "blocks": blocks,
                    },
                },
            },
            action={"decision": decision},
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["server", "sdk"])
@pytest.mark.parametrize("category", ["matches", "non_matches", "errors"])
@pytest.mark.parametrize("elapsed_seconds", [0.0, 0.0125])
async def test_completed_controls_report_elapsed_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
    evaluation_request: EvaluationRequest,
    context: Literal["server", "sdk"],
    category: str,
    elapsed_seconds: float,
) -> None:
    # Given: a completed control and a controlled clock instead of wall-clock assertions
    control = make_control(
        context=context,
        matched=category == "matches",
        raises_error=category == "errors",
    )
    clock = Mock(side_effect=[10.0, 10.0 + elapsed_seconds])
    monkeypatch.setattr("agent_control_engine.core.time.perf_counter", clock)

    # When: evaluating via the public engine entrypoint
    response = await ControlEngine([control], context=context).process(evaluation_request)

    # Then: all completed outcome categories retain their own duration, including zero
    results = getattr(response, category)
    assert results is not None
    assert len(results) == 1
    assert results[0].execution_duration_ms == pytest.approx(elapsed_seconds * 1000)
    assert results[0].result.matched is (category == "matches")
    assert bool(results[0].result.error) is (category == "errors")
    assert response.is_safe is True


@pytest.mark.asyncio
async def test_parallel_controls_keep_individual_durations(
    monkeypatch: pytest.MonkeyPatch, evaluation_request: EvaluationRequest
) -> None:
    # Given: parallel controls start together and complete at different clock readings
    clock = Mock(side_effect=[10.0, 10.0, 10.0125, 10.025])
    monkeypatch.setattr("agent_control_engine.core.time.perf_counter", clock)
    controls = [make_control(1), make_control(2)]

    # When: evaluating both controls in the same engine request
    response = await ControlEngine(controls).process(evaluation_request)

    # Then: each control reports its own elapsed time rather than the batch duration
    assert response.non_matches is not None
    durations = {result.control_id: result.execution_duration_ms for result in response.non_matches}
    assert durations == pytest.approx({1: 12.5, 2: 25.0})


@pytest.mark.asyncio
async def test_condition_traversal_error_retains_elapsed_duration(
    monkeypatch: pytest.MonkeyPatch, evaluation_request: EvaluationRequest
) -> None:
    # Given: an internal traversal failure forced to exercise the outer error handler
    engine = ControlEngine([make_control(decision="deny")])
    monkeypatch.setattr(
        engine, "_evaluate_condition", AsyncMock(side_effect=ValueError("condition failed"))
    )
    clock = Mock(side_effect=[10.0, 10.007])
    monkeypatch.setattr("agent_control_engine.core.time.perf_counter", clock)

    # When: evaluating via the public engine entrypoint
    response = await engine.process(evaluation_request)

    # Then: the completed error is timed and still fails closed
    assert response.is_safe is False
    assert response.errors is not None
    assert len(response.errors) == 1
    assert response.errors[0].execution_duration_ms == pytest.approx(7.0)
    assert response.errors[0].result.error == "ValueError: condition failed"


@pytest.mark.asyncio
async def test_timed_out_evaluation_retains_elapsed_duration(
    monkeypatch: pytest.MonkeyPatch, evaluation_request: EvaluationRequest
) -> None:
    # Given: a blocking evaluator with a bounded timeout and a controlled elapsed clock
    monkeypatch.setattr(DurationEvaluator, "get_timeout_seconds", lambda self: 0.001)
    clock = Mock(side_effect=[10.0, 10.001])
    monkeypatch.setattr("agent_control_engine.core.time.perf_counter", clock)

    # When: the evaluator times out without producing a normal result
    response = await ControlEngine([make_control(blocks=True, decision="deny")]).process(
        evaluation_request
    )

    # Then: the timeout error is a completed evaluation with an elapsed duration
    assert response.is_safe is False
    assert response.errors is not None
    assert len(response.errors) == 1
    assert response.errors[0].execution_duration_ms == pytest.approx(1.0)
    assert response.errors[0].result.error is not None
    assert response.errors[0].result.error.startswith("TimeoutError:")


@pytest.mark.asyncio
async def test_cancelled_controls_do_not_report_partial_durations(
    monkeypatch: pytest.MonkeyPatch, evaluation_request: EvaluationRequest
) -> None:
    # Given: a blocking control that is cancelled by a completed deny control
    clock = Mock(side_effect=[10.0, 10.0, 10.020])
    monkeypatch.setattr("agent_control_engine.core.time.perf_counter", clock)
    controls = [make_control(1, blocks=True), make_control(2, matched=True, decision="deny")]

    # When: a deny match cancels the unfinished evaluation
    response = await ControlEngine(controls).process(evaluation_request)

    # Then: only the completed deny is returned, with no fabricated cancelled result
    assert response.is_safe is False
    assert response.matches is not None
    assert len(response.matches) == 1
    assert response.matches[0].control_id == 2
    assert response.matches[0].execution_duration_ms == pytest.approx(20.0)
    assert response.non_matches is None
    assert response.errors is None
    assert clock.call_count == 3


@pytest.mark.asyncio
async def test_skipped_control_does_not_start_duration_measurement(
    monkeypatch: pytest.MonkeyPatch, evaluation_request: EvaluationRequest
) -> None:
    # Given: a disabled control that must not evaluate
    control = make_control()
    control.control.enabled = False
    clock = Mock(side_effect=AssertionError("skipped control must not be timed"))
    monkeypatch.setattr("agent_control_engine.core.time.perf_counter", clock)

    # When: processing a request without applicable controls
    response = await ControlEngine([control]).process(evaluation_request)

    # Then: there are no results or clock reads for the skipped control
    assert response.matches is None
    assert response.non_matches is None
    assert response.errors is None
    clock.assert_not_called()


@pytest.mark.asyncio
async def test_precheck_error_has_no_execution_duration(
    monkeypatch: pytest.MonkeyPatch, evaluation_request: EvaluationRequest
) -> None:
    # Given: validation is bypassed to exercise the defensive invalid-regex precheck
    control = make_control()
    payload = control.control.model_dump()
    payload["scope"]["step_name_regex"] = "[invalid(regex"
    control.control = ControlDefinition.model_validate(
        payload, context={"allow_invalid_step_name_regex": True}
    )
    clock = Mock(side_effect=AssertionError("precheck failure must not be timed"))
    monkeypatch.setattr("agent_control_engine.core.time.perf_counter", clock)

    # When: processing a control that fails before evaluation
    response = await ControlEngine([control]).process(evaluation_request)

    # Then: the error retains an unknown duration rather than zero
    assert response.errors is not None
    assert len(response.errors) == 1
    assert response.errors[0].execution_duration_ms is None
    clock.assert_not_called()
