"""Tests for check_evaluation behavior."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from agent_control import evaluation
from agent_control.evaluation import EvaluationResult


@pytest.mark.asyncio
async def test_check_evaluation_requires_step_name_before_server_call():
    """Typed request validation should reject steps without a name before server call."""

    client = MagicMock()
    client.http_client = AsyncMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValidationError):
        await evaluation.check_evaluation(
            client=client,
            agent_name=UUID("00000000-0000-0000-0000-000000000001"),
            step={"type": "llm", "input": "hello"},
            stage="pre",
        )

    client.http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_check_evaluation_returns_result_model():
    """check_evaluation returns a parsed EvaluationResult."""
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"is_safe": True, "confidence": 0.75, "reason": "ok"}

    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock(return_value=DummyResponse())

    result = await evaluation.check_evaluation(
        client=client,
        agent_name="Agent-Example_01",
        step={"type": "llm", "name": "chat", "input": "hello"},
        stage="pre",
    )

    assert result.is_safe is True
    assert result.confidence == 0.75
    assert result.reason == "ok"
    client.http_client.post.assert_awaited_once_with(
        "/api/v1/evaluation",
        json={
            "agent_name": "agent-example_01",
            "step": {
                "type": "llm",
                "name": "chat",
                "input": "hello",
                "output": None,
                "context": None,
            },
            "stage": "pre",
            "target_type": None,
            "target_id": None,
        },
        headers=None,
    )


@pytest.mark.asyncio
async def test_evaluate_controls_requires_server_url():
    """evaluate_controls should require server_url to be configured."""
    with patch("agent_control.state.server_url", None):
        with pytest.raises(RuntimeError, match="Server URL not configured"):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_name="test-bot",
            )


@pytest.mark.asyncio
async def test_evaluate_controls_with_explicit_agent_name(monkeypatch):
    """evaluate_controls should call check_evaluation_with_local."""
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            result = await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_name="test-bot",
            )

    assert result.is_safe is True
    assert result.confidence == 1.0
    mock_check.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_controls_with_context(monkeypatch):
    """evaluate_controls should pass context through to evaluation."""
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                context={"user_id": "123"},
                stage="pre",
                agent_name="test-bot",
            )

    assert mock_check.call_args is not None


@pytest.mark.asyncio
async def test_check_evaluation_forwards_target_context():
    """When target_type and target_id are supplied, they are forwarded to the server."""

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"is_safe": True, "confidence": 1.0}

    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock(return_value=DummyResponse())

    await evaluation.check_evaluation(
        client=client,
        agent_name="Agent-Example_01",
        step={"type": "llm", "name": "chat", "input": "hello"},
        stage="pre",
        target_type="env",
        target_id="prod",
    )

    sent = client.http_client.post.await_args.kwargs["json"]
    assert sent["target_type"] == "env"
    assert sent["target_id"] == "prod"


@pytest.mark.asyncio
async def test_evaluate_controls_forwards_target_context(monkeypatch):
    """evaluate_controls passes target_type/target_id into check_evaluation_with_local."""
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_name="test-bot",
                target_type="env",
                target_id="prod",
            )

    kwargs = mock_check.call_args.kwargs
    assert kwargs["target_type"] == "env"
    assert kwargs["target_id"] == "prod"


@pytest.mark.asyncio
async def test_target_bearing_request_uses_target_bound_controls():
    """A target-bearing request fetches the effective target-bound controls
    from the server and ignores cached agent-attached controls.

    Without this, the SDK would resolve from agent-cached controls (which
    target-bearing requests must NOT consult) and return a result derived
    from the wrong attachment set.
    """

    class TargetControlsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"controls": []}

    class EvaluationDummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"is_safe": True, "confidence": 1.0}

    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock(return_value=TargetControlsResponse())
    client.http_client.post = AsyncMock(return_value=EvaluationDummyResponse())

    # A cached agent-attached control that would have run locally for an
    # agent-only request. Target-bearing flow must ignore this.
    cached_local_control = {
        "id": 1,
        "name": "local-control",
        "control": {
            "description": "local",
            "enabled": True,
            "execution": "sdk",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {"name": "regex", "config": {"pattern": "x"}},
            },
            "action": {"decision": "deny"},
        },
    }

    await evaluation.check_evaluation_with_local(
        client=client,
        agent_name="mytestagent01",
        step={"type": "llm", "name": "chat", "input": "x"},
        stage="pre",
        controls=[cached_local_control],
        target_type="env",
        target_id="prod",
    )

    # Effective target controls were fetched once, not the cached set.
    client.http_client.get.assert_awaited_once()
    fetch_url = client.http_client.get.await_args.args[0]
    fetch_params = client.http_client.get.await_args.kwargs["params"]
    assert fetch_url == "/api/v1/control-bindings/effective"
    assert fetch_params == {"target_type": "env", "target_id": "prod"}


@pytest.mark.asyncio
async def test_target_bearing_request_runs_sdk_execution_controls_locally():
    """A target-bearing request runs ``execution='sdk'`` controls locally
    (using controls fetched from /control-bindings/effective) and only sends
    server-execution controls to the evaluation endpoint."""

    target_local_control = {
        "id": 1,
        "name": "target-local-control",
        "control": {
            "description": "local",
            "enabled": True,
            "execution": "sdk",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {"name": "regex", "config": {"pattern": "block"}},
            },
            "action": {"decision": "deny"},
        },
    }

    class TargetControlsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"controls": [target_local_control]}

    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock(return_value=TargetControlsResponse())
    post = AsyncMock()
    client.http_client.post = post

    result = await evaluation.check_evaluation_with_local(
        client=client,
        agent_name="mytestagent01",
        step={"type": "llm", "name": "chat", "input": "block this"},
        stage="pre",
        controls=[],  # cached agent set is unused for target-bearing
        target_type="env",
        target_id="prod",
    )

    # Local engine produced a deny without ever calling the server.
    assert result.is_safe is False
    post.assert_not_awaited()
