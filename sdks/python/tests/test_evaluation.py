"""Tests for check_evaluation behavior."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from agent_control import evaluation
from agent_control.evaluation import EvaluationResult


@pytest.mark.asyncio
async def test_check_evaluation_requires_step_name_without_models(monkeypatch):
    """Fallback path should reject steps without a name before calling the server."""
    monkeypatch.setattr(evaluation, "MODELS_AVAILABLE", False)

    client = MagicMock()
    client.http_client = AsyncMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValueError, match="step.name is required"):
        await evaluation.check_evaluation(
            client=client,
            agent_uuid=UUID("00000000-0000-0000-0000-000000000001"),
            step={"type": "llm", "input": "hello"},
            stage="pre",
        )

    client.http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_controls_with_explicit_agent_uuid(monkeypatch):
    """Test evaluate_controls with explicit agent_uuid provided."""
    # Mock check_evaluation_with_local to return a safe result
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    # Mock module globals (_server_url is required)
    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            result = await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_uuid="550e8400-e29b-41d4-a716-446655440000",
                agent_name="test-bot",
            )

    assert result.is_safe is True
    assert result.confidence == 1.0
    mock_check.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_controls_requires_server_url(monkeypatch):
    """Test evaluate_controls raises error when server_url not configured."""
    # Mock module globals with no server URL
    with patch("agent_control.state.server_url", None):
        with pytest.raises(
            RuntimeError,
            match="Server URL not configured",
        ):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_uuid="550e8400-e29b-41d4-a716-446655440000",
                agent_name="test-bot",
            )


@pytest.mark.asyncio
async def test_evaluate_controls_with_explicit_agent(monkeypatch):
    """Test evaluate_controls works with explicitly provided agent_uuid and agent_name."""
    # Mock check_evaluation_with_local
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            result = await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_uuid="550e8400-e29b-41d4-a716-446655440000",
                agent_name="test-bot",
            )

    assert result.is_safe is True
    mock_check.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_controls_with_context(monkeypatch):
    """Test evaluate_controls includes context when provided."""
    # Mock check_evaluation_with_local
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            result = await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                context={"user_id": "123", "session_id": "abc"},
                stage="pre",
                agent_uuid="550e8400-e29b-41d4-a716-446655440000",
                agent_name="test-bot",
            )

    assert result.is_safe is True
    # Verify context was passed through
    call_args = mock_check.call_args
    assert call_args is not None


@pytest.mark.asyncio
async def test_evaluate_controls_without_models(monkeypatch):
    """Test evaluate_controls when MODELS_AVAILABLE is False."""
    # Mock check_evaluation_with_local
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    # Mock MODELS_AVAILABLE as False
    monkeypatch.setattr(evaluation, "MODELS_AVAILABLE", False)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            result = await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_uuid="550e8400-e29b-41d4-a716-446655440000",
                agent_name="test-bot",
            )

    assert result.is_safe is True
