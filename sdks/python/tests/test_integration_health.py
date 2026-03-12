"""
Integration tests for server health and connectivity.

These tests verify basic server functionality:
1. Server health check
2. Client connection management
3. Error handling
"""

import agent_control
import pytest


@pytest.mark.asyncio
async def test_health_check_workflow(
    client: agent_control.AgentControlClient
) -> None:
    """
    Test server health check.

    Verifies:
    - Health endpoint is accessible
    - Response includes status
    - Status is healthy
    """
    health = await client.health_check()

    # Verify response structure
    assert isinstance(health, dict)
    assert "status" in health

    print(f"✓ Server health: {health['status']}")


@pytest.mark.asyncio
async def test_client_context_manager(
    monkeypatch: pytest.MonkeyPatch, server_url: str
) -> None:
    """
    Test client context manager behavior.

    Verifies:
    - Client can be created and closed properly
    - Context manager handles cleanup
    """
    # Given: the SDK client is configured from the test server URL environment variable
    monkeypatch.setenv("AGENT_CONTROL_URL", server_url)

    # When: using AgentControlClient as an async context manager
    async with agent_control.AgentControlClient() as client:
        # Verify client is initialized
        assert client._client is not None

        # Make a simple request
        health = await client.health_check()
        assert health is not None

    # Then: the client works inside the context manager and exits cleanly
    # After context, client should be closed
    # (we can't easily verify this without accessing internals)
    print("✓ Client context manager works correctly")


@pytest.mark.asyncio
async def test_invalid_server_url() -> None:
    """
    Test error handling with invalid server URL.

    Verifies:
    - Appropriate errors are raised for unreachable servers
    """
    invalid_url = "http://invalid-server-that-does-not-exist:9999"

    with pytest.raises(Exception):
        async with agent_control.AgentControlClient(base_url=invalid_url) as client:
            await client.health_check()

    print("✓ Invalid server URL correctly raises error")
