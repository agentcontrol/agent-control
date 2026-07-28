"""Validation tests for agent_control.init()."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agent_control_models import ControlMatch as ModelControlMatch
from agent_control_models import ControlScope as ModelControlScope
from agent_control_models import EvaluatorResult as ModelEvaluatorResult

import agent_control
from agent_control._state import state


def test_init_rejects_invalid_agent_name() -> None:
    with pytest.raises(ValueError, match="at least 10 characters"):
        agent_control.init(agent_name="short")


def test_init_rejects_negative_policy_refresh_interval() -> None:
    with pytest.raises(ValueError, match="policy_refresh_interval_seconds must be >= 0"):
        agent_control.init(
            agent_name="negative-interval-agent",
            policy_refresh_interval_seconds=-1,
        )


def test_init_rejects_partial_target_pair() -> None:
    """target_type and target_id must be supplied together."""
    with pytest.raises(ValueError, match="target_type and target_id must be supplied together"):
        agent_control.init(
            agent_name="partial-target-agent",
            target_type="env",  # target_id omitted
        )

    with pytest.raises(ValueError, match="target_type and target_id must be supplied together"):
        agent_control.init(
            agent_name="partial-target-agent",
            target_id="prod",  # target_type omitted
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


def test_init_stores_runtime_token_header_in_state() -> None:
    """HYBIM-741: init() retains runtime_token_header in session state so the
    evaluation clients it creates ride the configured header (not only the
    process-wide env var)."""
    health_check_mock = AsyncMock(return_value={"status": "healthy"})
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    try:
        with patch(
            "agent_control.__init__.AgentControlClient.health_check",
            new=health_check_mock,
        ), patch(
            "agent_control.__init__.agents.register_agent",
            new=register_agent_mock,
        ):
            agent_control.init(
                agent_name=f"agent-{uuid4().hex[:12]}",
                runtime_token_header="X-Agent-Control-Runtime-Token",
                policy_refresh_interval_seconds=0,
            )

        assert state.runtime_token_header == "X-Agent-Control-Runtime-Token"
    finally:
        agent_control._reset_state()


def test_init_defaults_runtime_token_header_to_none() -> None:
    """Unset: state carries None so the client falls back to env/default."""
    health_check_mock = AsyncMock(return_value={"status": "healthy"})
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    try:
        with patch(
            "agent_control.__init__.AgentControlClient.health_check",
            new=health_check_mock,
        ), patch(
            "agent_control.__init__.agents.register_agent",
            new=register_agent_mock,
        ):
            agent_control.init(
                agent_name=f"agent-{uuid4().hex[:12]}",
                policy_refresh_interval_seconds=0,
            )

        assert state.runtime_token_header is None
    finally:
        agent_control._reset_state()
