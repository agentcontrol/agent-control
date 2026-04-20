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
async def test_check_evaluation_forwards_target_fields_when_supplied():
    """target_type and target_id land in the outgoing request body when set."""

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
        target_type="environment",
        target_id="env-prod-123",
    )

    sent_payload = client.http_client.post.await_args.kwargs["json"]
    assert sent_payload["target_type"] == "environment"
    assert sent_payload["target_id"] == "env-prod-123"


@pytest.mark.asyncio
async def test_check_evaluation_rejects_half_target_context():
    """Server-side pairing rule must be enforced client-side via model validation."""
    client = MagicMock()
    client.http_client = AsyncMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValidationError):
        await evaluation.check_evaluation(
            client=client,
            agent_name="Agent-Example_01",
            step={"type": "llm", "name": "chat", "input": "hello"},
            stage="pre",
            target_type="environment",
        )

    client.http_client.post.assert_not_called()


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
async def test_evaluate_controls_forwards_target_fields(monkeypatch):
    """target_type and target_id flow through to check_evaluation_with_local."""
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
                target_type="environment",
                target_id="env-prod-123",
            )

    forwarded = mock_check.call_args.kwargs
    assert forwarded["target_type"] == "environment"
    assert forwarded["target_id"] == "env-prod-123"


@pytest.mark.asyncio
async def test_evaluate_controls_defaults_target_fields_to_none(monkeypatch):
    """Omitting target fields sends None through so the existing path stays unchanged."""
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
            )

    forwarded = mock_check.call_args.kwargs
    assert forwarded["target_type"] is None
    assert forwarded["target_id"] is None
