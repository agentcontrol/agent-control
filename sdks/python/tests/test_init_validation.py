"""Validation tests for agent_control.init()."""

import pytest
from agent_control_models import ControlMatch as ModelControlMatch
from agent_control_models import ControlScope as ModelControlScope
from agent_control_models import EvaluatorResult as ModelEvaluatorResult

import agent_control


def test_init_rejects_invalid_uuid() -> None:
    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        agent_control.init(agent_name="Invalid UUID Agent", agent_id="not-a-uuid")


def test_init_exports_control_scope() -> None:
    assert agent_control.ControlScope is ModelControlScope
    assert "ControlScope" in agent_control.__all__


def test_init_exports_control_match() -> None:
    assert agent_control.ControlMatch is ModelControlMatch
    assert "ControlMatch" in agent_control.__all__


def test_init_exports_evaluator_result() -> None:
    assert agent_control.EvaluatorResult is ModelEvaluatorResult
    assert "EvaluatorResult" in agent_control.__all__
