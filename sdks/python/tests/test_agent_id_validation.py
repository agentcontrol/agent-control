"""SDK agent_id validation behavior tests."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import agent_control
import pytest
from agent_control import agents, policies


class DummyResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"ok": True}


@pytest.mark.asyncio
async def test_get_agent_rejects_invalid_uuid() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock()

    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        await agents.get_agent(client, "not-a-uuid")

    client.http_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_policies_rejects_invalid_uuid() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock()

    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        await agents.get_agent_policies(client, "not-a-uuid")

    client.http_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_remove_agent_policies_rejects_invalid_uuid() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.delete = AsyncMock()

    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        await agents.remove_agent_policies(client, "not-a-uuid")

    client.http_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_remove_agent_policy_association_rejects_invalid_uuid() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.delete = AsyncMock()

    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        await agents.remove_agent_policy_association(
            client, "not-a-uuid", policy_id=1
        )

    client.http_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_assign_policy_rejects_invalid_uuid() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        await policies.assign_policy_to_agent(client, "not-a-uuid", policy_id=1)

    client.http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_accepts_uuid_object() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock(return_value=DummyResponse())

    agent_id = uuid4()
    await agents.get_agent(client, agent_id)

    client.http_client.get.assert_awaited_once_with(f"/api/v1/agents/{agent_id}")


@pytest.mark.asyncio
async def test_clear_agent_policies_calls_agents_module() -> None:
    agent_id = uuid4()

    with patch(
        "agent_control.__init__.agents.remove_agent_policies", new_callable=AsyncMock
    ) as mock_remove:
        mock_remove.return_value = {"success": True}

        result = await agent_control.clear_agent_policies(agent_id)

    assert result == {"success": True}
    assert mock_remove.await_count == 1
    assert mock_remove.await_args.args[1] == agent_id
