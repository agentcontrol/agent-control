"""Unit tests for AgentControlClient configuration and version warnings."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from agent_control.client import AgentControlClient, sdk_version


def test_client_uses_agent_control_url_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: AGENT_CONTROL_URL is set in the environment
    monkeypatch.setenv("AGENT_CONTROL_URL", "http://example.test:9000/")

    # When: constructing a client without an explicit base URL
    client = AgentControlClient()

    # Then: the client uses the environment-provided server URL
    assert client.base_url == "http://example.test:9000"


def test_explicit_base_url_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: AGENT_CONTROL_URL is set but an explicit base URL is also provided
    monkeypatch.setenv("AGENT_CONTROL_URL", "http://env.test:9000")

    # When: constructing the client with an explicit base URL
    client = AgentControlClient(base_url="http://explicit.test:8000/")

    # Then: the explicit base URL wins
    assert client.base_url == "http://explicit.test:8000"


def test_get_headers_include_sdk_metadata_and_api_key() -> None:
    # Given: a client configured with an API key
    client = AgentControlClient(api_key="test-key")

    # When: building request headers
    headers = client._get_headers()

    # Then: SDK metadata and authentication headers are included
    assert headers["X-Agent-Control-SDK"] == "python"
    assert headers["X-Agent-Control-SDK-Version"] == sdk_version
    assert headers["X-API-Key"] == "test-key"


@pytest.mark.asyncio
async def test_check_server_version_warns_once_on_major_mismatch() -> None:
    # Given: a server response with a mismatched major version header
    client = AgentControlClient()
    response = httpx.Response(
        200,
        headers={"X-Agent-Control-Server-Version": "999.1.0"},
    )

    # When: version checking runs twice for the same mismatch
    with patch("agent_control.client._logger.warning") as mock_warning:
        await client._check_server_version(response)
        await client._check_server_version(response)

    # Then: the warning is emitted only once
    mock_warning.assert_called_once()


@pytest.mark.asyncio
async def test_check_server_version_does_not_warn_on_matching_major() -> None:
    # Given: a server response whose major version matches the SDK major version
    client = AgentControlClient()
    matching_major = sdk_version.split(".", 1)[0]
    response = httpx.Response(
        200,
        headers={"X-Agent-Control-Server-Version": f"{matching_major}.99.0"},
    )

    # When: version checking runs
    with patch("agent_control.client._logger.warning") as mock_warning:
        await client._check_server_version(response)

    # Then: no warning is emitted
    mock_warning.assert_not_called()


@pytest.mark.asyncio
async def test_check_server_version_ignores_missing_header() -> None:
    # Given: a response without the server version header
    client = AgentControlClient()
    response = httpx.Response(200)

    # When: version checking runs
    with patch("agent_control.client._logger.warning") as mock_warning:
        await client._check_server_version(response)

    # Then: no warning is emitted
    mock_warning.assert_not_called()
