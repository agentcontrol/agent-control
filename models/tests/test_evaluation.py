"""Unit tests for EvaluationRequest target field pairing semantics."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_control_models import EvaluationRequest
from agent_control_models.agent import Step


def _step() -> Step:
    return Step(type="llm", name="chat", input="hello", output=None)


def test_both_target_fields_unset_is_valid() -> None:
    req = EvaluationRequest(
        agent_name="test-agent",
        step=_step(),
        stage="pre",
    )
    assert req.target_type is None
    assert req.target_id is None


def test_both_target_fields_set_is_valid() -> None:
    req = EvaluationRequest(
        agent_name="test-agent",
        step=_step(),
        stage="pre",
        target_type="environment",
        target_id="env-prod-123",
    )
    assert req.target_type == "environment"
    assert req.target_id == "env-prod-123"


def test_only_target_type_set_raises() -> None:
    with pytest.raises(ValidationError) as excinfo:
        EvaluationRequest(
            agent_name="test-agent",
            step=_step(),
            stage="pre",
            target_type="environment",
        )
    assert "target_type and target_id must be provided together" in str(excinfo.value)


def test_only_target_id_set_raises() -> None:
    with pytest.raises(ValidationError) as excinfo:
        EvaluationRequest(
            agent_name="test-agent",
            step=_step(),
            stage="pre",
            target_id="env-prod-123",
        )
    assert "target_type and target_id must be provided together" in str(excinfo.value)
