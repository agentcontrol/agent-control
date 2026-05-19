"""Unit tests for agent_control.control_bindings API wrappers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import agent_control
import pytest


@pytest.mark.asyncio
async def test_upsert_control_binding_by_key_calls_endpoint() -> None:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"binding_id": 123, "created": True, "enabled": True})
    client = SimpleNamespace(http_client=SimpleNamespace(put=AsyncMock(return_value=response)))

    result = await agent_control.control_bindings.upsert_control_binding_by_key(
        client,
        target_type="log_stream",
        target_id="ls-prod",
        control_id=456,
    )

    assert result["binding_id"] == 123
    client.http_client.put.assert_awaited_once_with(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": "log_stream",
            "target_id": "ls-prod",
            "control_id": 456,
            "enabled": True,
        },
    )


@pytest.mark.asyncio
async def test_update_control_binding_by_key_calls_endpoint() -> None:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"success": True, "enabled": False})
    client = SimpleNamespace(http_client=SimpleNamespace(patch=AsyncMock(return_value=response)))

    result = await agent_control.control_bindings.update_control_binding_by_key(
        client,
        target_type="log_stream",
        target_id="ls-prod",
        control_id=456,
        enabled=False,
    )

    assert result["enabled"] is False
    client.http_client.patch.assert_awaited_once_with(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": "log_stream",
            "target_id": "ls-prod",
            "control_id": 456,
            "enabled": False,
        },
    )


@pytest.mark.asyncio
async def test_delete_control_binding_by_key_calls_endpoint() -> None:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"deleted": True})
    client = SimpleNamespace(http_client=SimpleNamespace(post=AsyncMock(return_value=response)))

    result = await agent_control.control_bindings.delete_control_binding_by_key(
        client,
        target_type="log_stream",
        target_id="ls-prod",
        control_id=456,
    )

    assert result["deleted"] is True
    client.http_client.post.assert_awaited_once_with(
        "/api/v1/control-bindings/by-key:delete",
        json={
            "target_type": "log_stream",
            "target_id": "ls-prod",
            "control_id": 456,
        },
    )
