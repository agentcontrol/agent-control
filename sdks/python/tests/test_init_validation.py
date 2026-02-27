"""Validation tests for agent_control.init()."""

import agent_control
import pytest
from agent_control_models import ControlMatch as ModelControlMatch
from agent_control_models import ControlScope as ModelControlScope
from agent_control_models import EvaluatorResult as ModelEvaluatorResult


def test_init_rejects_invalid_agent_name() -> None:
    with pytest.raises(ValueError, match="at least 10 characters"):
        agent_control.init(agent_name="short")


def test_init_rejects_negative_policy_refresh_interval() -> None:
    with pytest.raises(ValueError, match="policy_refresh_interval_seconds must be >= 0"):
        agent_control.init(
            agent_name="negative-interval-agent",
            policy_refresh_interval_seconds=-1,
        )


def test_init_exports_control_scope() -> None:
    assert agent_control.ControlScope is ModelControlScope
    assert "ControlScope" in agent_control.__all__


def test_init_exports_control_match() -> None:
    assert agent_control.ControlMatch is ModelControlMatch
    assert "ControlMatch" in agent_control.__all__


def test_init_exports_evaluator_result() -> None:
    assert agent_control.EvaluatorResult is ModelEvaluatorResult
    assert "EvaluatorResult" in agent_control.__all__
