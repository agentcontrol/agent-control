"""Tests that init() surfaces server-side conflicts."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

import agent_control


def _make_conflict_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://localhost:8000/api/v1/agents/initAgent")
    response = httpx.Response(409, request=request)
    return httpx.HTTPStatusError(
        "Client error '409 Conflict' for url 'http://localhost:8000/api/v1/agents/initAgent'",
        request=request,
        response=response,
    )


def test_init_surfaces_uuid_conflict() -> None:
    conflict = _make_conflict_error()

    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=AsyncMock(return_value={"status": "healthy"}),
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=AsyncMock(side_effect=conflict),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            agent_control.init(
                agent_name="Init Conflict Agent",
                agent_id=str(uuid4()),
                agent_description="Testing init conflict handling",
            )
