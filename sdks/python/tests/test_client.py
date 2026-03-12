"""Unit tests for AgentControlClient configuration and version warnings."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from agent_control.client import AgentControlClient, sdk_version


def test_client_uses_agent_control_url_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_CONTROL_URL", "http://example.test:9000/")

    client = AgentControlClient()

    assert client.base_url == "http://example.test:9000"


def test_explicit_base_url_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_CONTROL_URL", "http://env.test:9000")

    client = AgentControlClient(base_url="http://explicit.test:8000/")

    assert client.base_url == "http://explicit.test:8000"


def test_get_headers_include_sdk_metadata_and_api_key() -> None:
    client = AgentControlClient(api_key="test-key")

    headers = client._get_headers()

    assert headers["X-Agent-Control-SDK"] == "python"
    assert headers["X-Agent-Control-SDK-Version"] == sdk_version
    assert headers["X-API-Key"] == "test-key"


@pytest.mark.asyncio
async def test_check_server_version_warns_once_on_major_mismatch() -> None:
    client = AgentControlClient()
    response = httpx.Response(
        200,
        headers={"X-Agent-Control-Server-Version": "999.1.0"},
    )

    with patch("agent_control.client._logger.warning") as mock_warning:
        await client._check_server_version(response)
        await client._check_server_version(response)

    mock_warning.assert_called_once()


@pytest.mark.asyncio
async def test_check_server_version_does_not_warn_on_matching_major() -> None:
    client = AgentControlClient()
    matching_major = sdk_version.split(".", 1)[0]
    response = httpx.Response(
        200,
        headers={"X-Agent-Control-Server-Version": f"{matching_major}.99.0"},
    )

    with patch("agent_control.client._logger.warning") as mock_warning:
        await client._check_server_version(response)

    mock_warning.assert_not_called()


@pytest.mark.asyncio
async def test_check_server_version_ignores_missing_header() -> None:
    client = AgentControlClient()
    response = httpx.Response(200)

    with patch("agent_control.client._logger.warning") as mock_warning:
        await client._check_server_version(response)

    mock_warning.assert_not_called()
