"""SDK agent name validation behavior tests."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from agent_control import agents, policies


class DummyResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"ok": True}


@pytest.mark.asyncio
async def test_get_agent_rejects_invalid_agent_name() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock()

    with pytest.raises(ValueError, match="at least 10 characters"):
        await agents.get_agent(client, "short")

    client.http_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_policy_rejects_invalid_agent_name() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock()

    with pytest.raises(ValueError, match="at least 10 characters"):
        await agents.get_agent_policy(client, "short")

    client.http_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_remove_agent_policy_rejects_invalid_agent_name() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.delete = AsyncMock()

    with pytest.raises(ValueError, match="at least 10 characters"):
        await agents.remove_agent_policy(client, "short")

    client.http_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_list_agents_normalizes_cursor() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock(return_value=DummyResponse())

    await agents.list_agents(client, cursor="Agent-Example_01", limit=5)

    client.http_client.get.assert_awaited_once_with(
        "/api/v1/agents",
        params={"limit": 5, "cursor": "agent-example_01"},
    )


@pytest.mark.asyncio
async def test_assign_policy_rejects_invalid_agent_name() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValueError, match="at least 10 characters"):
        await policies.assign_policy_to_agent(client, "short", policy_id=1)

    client.http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_normalizes_agent_name() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock(return_value=DummyResponse())

    agent_name = "Agent-Example_01"
    await agents.get_agent(client, agent_name)

    client.http_client.get.assert_awaited_once_with("/api/v1/agents/agent-example_01")


@pytest.mark.asyncio
async def test_get_agent_policy_normalizes_agent_name() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock(return_value=DummyResponse())

    await agents.get_agent_policy(client, "Agent-Example_01")

    client.http_client.get.assert_awaited_once_with("/api/v1/agents/agent-example_01/policy")


@pytest.mark.asyncio
async def test_remove_agent_policy_normalizes_agent_name() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.delete = AsyncMock(return_value=DummyResponse())

    await agents.remove_agent_policy(client, "Agent-Example_01")

    client.http_client.delete.assert_awaited_once_with("/api/v1/agents/agent-example_01/policy")
