"""SDK agent_id validation behavior tests."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent_control import agents


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
async def test_add_control_to_agent_rejects_invalid_uuid() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        await agents.add_control_to_agent(client, "not-a-uuid", control_id=1)

    client.http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_remove_control_from_agent_rejects_invalid_uuid() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.delete = AsyncMock()

    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        await agents.remove_control_from_agent(client, "not-a-uuid", control_id=1)

    client.http_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_accepts_uuid_object() -> None:
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.get = AsyncMock(return_value=DummyResponse())

    agent_id = uuid4()
    await agents.get_agent(client, agent_id)

    client.http_client.get.assert_awaited_once_with(f"/api/v1/agents/{agent_id}")
