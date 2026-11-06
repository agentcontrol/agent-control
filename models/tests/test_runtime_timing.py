"""Bounded timing callbacks must preserve evaluator behavior."""

import asyncio
from unittest.mock import Mock, patch

import pytest
from agent_control_models.runtime_timing import configure_runtime_timing, runtime_stage


@pytest.mark.parametrize(
    "error,outcome",
    [(None, "completed"), (ValueError, "error"), (asyncio.CancelledError, "cancelled")],
)
def test_stage_records_duration_and_original_outcome(error, outcome):
    # Given: a deterministic observer and clock at the shared timing seam.
    observer = Mock()
    configure_runtime_timing(observer)
    try:
        # When: an evaluator stage completes or propagates its original exception.
        with patch(
            "agent_control_models.runtime_timing.time.perf_counter", side_effect=[1.0, 1.125]
        ):
            if error is None:
                with runtime_stage("evaluator"):
                    pass
            else:
                with pytest.raises(error):
                    with runtime_stage("evaluator"):
                        raise error("original")
        # Then: one timing preserves both elapsed time and outcome.
        observer.assert_called_once_with("evaluator", 0.125, outcome)
    finally:
        configure_runtime_timing(None)


def test_disabled_or_failed_observer_does_not_change_evaluation():
    # Given: instrumentation is disabled or its observer fails.
    for observer in (None, Mock(side_effect=RuntimeError("observer"))):
        configure_runtime_timing(observer)
        try:
            # When: the evaluator completes normally.
            with runtime_stage("evaluator"):
                result = 42
            # Then: timing cannot fail the evaluator.
            assert result == 42
        finally:
            configure_runtime_timing(None)
