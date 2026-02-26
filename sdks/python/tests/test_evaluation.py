"""Tests for check_evaluation behavior."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from agent_control import evaluation


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
            agent_name=UUID("00000000-0000-0000-0000-000000000001"),
            step={"type": "llm", "input": "hello"},
            stage="pre",
        )

    client.http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_check_evaluation_returns_runtime_fallback_without_models(monkeypatch):
    """Fallback path should return an object with expected attributes."""
    monkeypatch.setattr(evaluation, "MODELS_AVAILABLE", False)

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
            "step": {"type": "llm", "name": "chat", "input": "hello"},
            "stage": "pre",
        },
    )
