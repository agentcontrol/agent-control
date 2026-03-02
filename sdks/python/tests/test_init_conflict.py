"""Tests that init() surfaces server-side conflicts."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import agent_control
import httpx
import pytest


def _make_conflict_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://localhost:8000/api/v1/agents/initAgent")
    response = httpx.Response(409, request=request)
    return httpx.HTTPStatusError(
        "Client error '409 Conflict' for url 'http://localhost:8000/api/v1/agents/initAgent'",
        request=request,
        response=response,
    )


def test_init_surfaces_conflict_response() -> None:
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
                agent_name=f"agent-{uuid4().hex[:12]}",
                agent_description="Testing init conflict handling",
                policy_refresh_interval_seconds=0,
            )
