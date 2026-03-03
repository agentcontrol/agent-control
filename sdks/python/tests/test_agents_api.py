"""Unit tests for agent_control.agents API wrappers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

import agent_control


@pytest.mark.asyncio
async def test_list_agent_controls_typed_calls_controls_endpoint() -> None:
    # GIVEN: a successful HTTP response payload for controls.
    response_payload = {"controls": []}
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value=response_payload)
    client = SimpleNamespace(http_client=SimpleNamespace(get=AsyncMock(return_value=response)))
    agent_name = str(uuid4())

    # WHEN: typed controls are requested.
    result = await agent_control.agents.list_agent_controls_typed(client, agent_name)

    # THEN: wrapper calls the expected endpoint and returns a typed result.
    client.http_client.get.assert_awaited_once_with(f"/api/v1/agents/{agent_name}/controls")
    assert isinstance(result.controls, list)


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
