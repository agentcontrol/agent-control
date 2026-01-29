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
            agent_uuid=UUID("00000000-0000-0000-0000-000000000001"),
            step={"type": "llm", "input": "hello"},
            stage="pre",
        )

    client.http_client.post.assert_not_called()
