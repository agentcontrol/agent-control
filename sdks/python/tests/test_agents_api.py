"""Unit tests for agent_control.agents API wrappers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

import agent_control


@pytest.mark.asyncio
async def test_list_agent_controls_typed_raises_when_models_unavailable() -> None:
    # GIVEN: model imports are unavailable in the agents module.
    client = SimpleNamespace(http_client=SimpleNamespace(get=AsyncMock()))

    # WHEN/THEN: calling the typed wrapper fails fast with RuntimeError.
    with patch("agent_control.agents.MODELS_AVAILABLE", False), patch(
        "agent_control.agents._AgentControlsResponse",
        None,
    ), pytest.raises(RuntimeError, match="requires agent_control_models"):
        await agent_control.agents.list_agent_controls_typed(client, str(uuid4()))

    # THEN: no HTTP request is attempted.
    client.http_client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_agent_controls_typed_validates_server_payload() -> None:
    # GIVEN: a successful HTTP response with an invalid payload shape.
    invalid_response = Mock()
    invalid_response.raise_for_status = Mock()
    invalid_response.json = Mock(return_value={"controls": "not-a-list"})

    client = SimpleNamespace(
        http_client=SimpleNamespace(get=AsyncMock(return_value=invalid_response)),
    )

    # WHEN/THEN: typed parsing raises ValidationError.
    with pytest.raises(ValidationError):
        await agent_control.agents.list_agent_controls_typed(client, str(uuid4()))

    # THEN: wrapper still called the expected endpoint.
    client.http_client.get.assert_awaited_once()
