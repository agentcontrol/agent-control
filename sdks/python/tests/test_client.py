"""Unit tests for AgentControlClient configuration and version warnings."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

from agent_control.client import AgentControlClient, sdk_version
from agent_control.runtime_auth import RuntimeTokenCache


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


def test_get_headers_include_sdk_metadata() -> None:
    # Given: a client configured with an API key
    client = AgentControlClient(api_key="test-key")

    # When: building request headers
    headers = client._get_headers()

    # Then: SDK metadata headers are included
    assert headers["X-Agent-Control-SDK"] == "python"
    assert headers["X-Agent-Control-SDK-Version"] == sdk_version
    assert "X-API-Key" not in headers


def test_client_rejects_negative_runtime_token_refresh_margin() -> None:
    with pytest.raises(ValueError, match="runtime_token_refresh_margin_seconds"):
        AgentControlClient(runtime_token_refresh_margin_seconds=-1)


@pytest.mark.asyncio
async def test_client_adds_api_key_auth_to_regular_requests() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        transport=transport,
    ) as client:
        response = await client.http_client.get("/api/v1/agents")

    assert response.status_code == 200
    assert seen_requests[0].headers["X-API-Key"] == "test-key"


@pytest.mark.asyncio
async def test_runtime_evaluation_exchanges_and_caches_bearer_token() -> None:
    exchange_calls = 0
    evaluation_authorization_headers: list[str | None] = []
    evaluation_api_key_headers: list[str | None] = []
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchange_calls
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            exchange_calls += 1
            assert request.headers["X-API-Key"] == "test-key"
            return httpx.Response(
                200,
                json={
                    "token": "runtime-token",
                    "expires_at": expires_at,
                    "target_type": "log_stream",
                    "target_id": "ls-1",
                    "scopes": ["runtime.use"],
                },
            )

        evaluation_authorization_headers.append(request.headers.get("Authorization"))
        evaluation_api_key_headers.append(request.headers.get("X-API-Key"))
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="auto",
        transport=transport,
    ) as client:
        for _ in range(2):
            response = await client.post_runtime_evaluation(
                json={"target_type": "log_stream", "target_id": "ls-1"},
                target_type="log_stream",
                target_id="ls-1",
            )
            assert response.status_code == 200

    assert exchange_calls == 1
    assert evaluation_authorization_headers == ["Bearer runtime-token", "Bearer runtime-token"]
    assert evaluation_api_key_headers == [None, None]


@pytest.mark.asyncio
async def test_runtime_evaluation_single_flights_cold_cache_exchange() -> None:
    exchange_calls = 0
    evaluation_authorization_headers: list[str | None] = []
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchange_calls
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            exchange_calls += 1
            await asyncio.sleep(0.01)
            return httpx.Response(
                200,
                json={
                    "token": "runtime-token",
                    "expires_at": expires_at,
                    "target_type": "log_stream",
                    "target_id": "ls-1",
                    "scopes": ["runtime.use"],
                },
            )

        evaluation_authorization_headers.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="jwt",
        transport=transport,
    ) as client:
        responses = await asyncio.gather(
            *(
                client.post_runtime_evaluation(
                    json={"target_type": "log_stream", "target_id": "ls-1"},
                    target_type="log_stream",
                    target_id="ls-1",
                )
                for _ in range(5)
            )
        )

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 200]
    assert exchange_calls == 1
    assert evaluation_authorization_headers == ["Bearer runtime-token"] * 5


@pytest.mark.asyncio
async def test_runtime_evaluation_refreshes_token_before_expiry() -> None:
    exchange_tokens = ["short-token", "fresh-token"]
    exchange_expiries = [
        (datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
        (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    ]
    evaluation_authorization_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            return httpx.Response(
                200,
                json={
                    "token": exchange_tokens.pop(0),
                    "expires_at": exchange_expiries.pop(0),
                    "target_type": "log_stream",
                    "target_id": "ls-1",
                    "scopes": ["runtime.use"],
                },
            )

        evaluation_authorization_headers.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="jwt",
        runtime_token_refresh_margin_seconds=30,
        transport=transport,
    ) as client:
        for _ in range(2):
            response = await client.post_runtime_evaluation(
                json={"target_type": "log_stream", "target_id": "ls-1"},
                target_type="log_stream",
                target_id="ls-1",
            )
            assert response.status_code == 200

    assert exchange_tokens == []
    assert evaluation_authorization_headers == [
        "Bearer short-token",
        "Bearer fresh-token",
    ]


@pytest.mark.asyncio
async def test_runtime_token_cache_is_scoped_to_server_url() -> None:
    exchange_paths: list[str] = []
    authorization_headers: list[str | None] = []
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    cache = RuntimeTokenCache()

    def handler(request: httpx.Request) -> httpx.Response:
        server_url = f"{request.url.scheme}://{request.url.host}"
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            exchange_paths.append(server_url)
            return httpx.Response(
                200,
                json={
                    "token": f"{request.url.host}-token",
                    "expires_at": expires_at,
                    "target_type": "log_stream",
                    "target_id": "ls-1",
                    "scopes": ["runtime.use"],
                },
            )

        authorization_headers.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    for base_url in ("https://server-a.test", "https://server-b.test"):
        async with AgentControlClient(
            base_url=base_url,
            api_key="test-key",
            runtime_auth_mode="jwt",
            runtime_token_cache=cache,
            transport=transport,
        ) as client:
            response = await client.post_runtime_evaluation(
                json={"target_type": "log_stream", "target_id": "ls-1"},
                target_type="log_stream",
                target_id="ls-1",
            )
            assert response.status_code == 200

    assert exchange_paths == ["https://server-a.test", "https://server-b.test"]
    assert authorization_headers == [
        "Bearer server-a.test-token",
        "Bearer server-b.test-token",
    ]


@pytest.mark.asyncio
async def test_runtime_evaluation_auto_falls_back_to_api_key_when_exchange_unavailable() -> None:
    exchange_calls = 0
    evaluation_api_key_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchange_calls
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            exchange_calls += 1
            return httpx.Response(503, json={"detail": "runtime auth disabled"})

        evaluation_api_key_headers.append(request.headers.get("X-API-Key"))
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="auto",
        transport=transport,
    ) as client:
        for _ in range(2):
            response = await client.post_runtime_evaluation(
                json={"target_type": "log_stream", "target_id": "ls-1"},
                target_type="log_stream",
                target_id="ls-1",
            )
            assert response.status_code == 200

    assert exchange_calls == 1
    assert evaluation_api_key_headers == ["test-key", "test-key"]


@pytest.mark.asyncio
async def test_runtime_evaluation_auto_without_target_uses_api_key_path() -> None:
    exchange_calls = 0
    evaluation_api_key_headers: list[str | None] = []
    evaluation_authorization_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchange_calls
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            exchange_calls += 1
            return httpx.Response(200, json={})

        evaluation_api_key_headers.append(request.headers.get("X-API-Key"))
        evaluation_authorization_headers.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="auto",
        transport=transport,
    ) as client:
        response = await client.post_runtime_evaluation(json={})

    assert response.status_code == 200
    assert exchange_calls == 0
    assert evaluation_api_key_headers == ["test-key"]
    assert evaluation_authorization_headers == [None]


@pytest.mark.asyncio
async def test_runtime_evaluation_retries_once_after_unauthorized_token() -> None:
    exchange_tokens = ["expired-token", "fresh-token"]
    evaluation_authorization_headers: list[str | None] = []
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            token = exchange_tokens.pop(0)
            return httpx.Response(
                200,
                json={
                    "token": token,
                    "expires_at": expires_at,
                    "target_type": "log_stream",
                    "target_id": "ls-1",
                    "scopes": ["runtime.use"],
                },
            )

        authorization = request.headers.get("Authorization")
        evaluation_authorization_headers.append(authorization)
        if authorization == "Bearer expired-token":
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="jwt",
        transport=transport,
    ) as client:
        response = await client.post_runtime_evaluation(
            json={"target_type": "log_stream", "target_id": "ls-1"},
            target_type="log_stream",
            target_id="ls-1",
        )

    assert response.status_code == 200
    assert evaluation_authorization_headers == [
        "Bearer expired-token",
        "Bearer fresh-token",
    ]
    assert exchange_tokens == []


@pytest.mark.asyncio
async def test_runtime_evaluation_does_not_auto_fallback_after_unauthorized_token() -> None:
    exchange_attempt = 0
    evaluation_authorization_headers: list[str | None] = []
    evaluation_api_key_headers: list[str | None] = []
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchange_attempt
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            exchange_attempt += 1
            if exchange_attempt == 1:
                return httpx.Response(
                    200,
                    json={
                        "token": "expired-token",
                        "expires_at": expires_at,
                        "target_type": "log_stream",
                        "target_id": "ls-1",
                        "scopes": ["runtime.use"],
                    },
                )
            return httpx.Response(503, json={"detail": "runtime auth disabled"})

        evaluation_authorization_headers.append(request.headers.get("Authorization"))
        evaluation_api_key_headers.append(request.headers.get("X-API-Key"))
        return httpx.Response(401, json={"detail": "expired"})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="auto",
        transport=transport,
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.post_runtime_evaluation(
                json={"target_type": "log_stream", "target_id": "ls-1"},
                target_type="log_stream",
                target_id="ls-1",
            )

    assert exc_info.value.response.status_code == 503
    assert exchange_attempt == 2
    assert evaluation_authorization_headers == ["Bearer expired-token"]
    assert evaluation_api_key_headers == [None]


@pytest.mark.asyncio
async def test_runtime_evaluation_returns_second_unauthorized_response() -> None:
    exchange_tokens = ["expired-token", "still-expired-token"]
    evaluation_authorization_headers: list[str | None] = []
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            return httpx.Response(
                200,
                json={
                    "token": exchange_tokens.pop(0),
                    "expires_at": expires_at,
                    "target_type": "log_stream",
                    "target_id": "ls-1",
                    "scopes": ["runtime.use"],
                },
            )

        evaluation_authorization_headers.append(request.headers.get("Authorization"))
        return httpx.Response(401, json={"detail": "expired"})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="jwt",
        transport=transport,
    ) as client:
        response = await client.post_runtime_evaluation(
            json={"target_type": "log_stream", "target_id": "ls-1"},
            target_type="log_stream",
            target_id="ls-1",
        )

    assert response.status_code == 401
    assert exchange_tokens == []
    assert evaluation_authorization_headers == [
        "Bearer expired-token",
        "Bearer still-expired-token",
    ]


@pytest.mark.asyncio
async def test_runtime_evaluation_jwt_mode_requires_target_context() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="jwt",
        transport=transport,
    ) as client:
        with pytest.raises(RuntimeError, match="requires target_type and target_id"):
            await client.post_runtime_evaluation(json={})


@pytest.mark.asyncio
async def test_runtime_exchange_rejects_non_object_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/runtime-token-exchange":
            return httpx.Response(200, json=["not", "an", "object"])
        return httpx.Response(200, json={"is_safe": True, "confidence": 1.0})

    transport = httpx.MockTransport(handler)

    async with AgentControlClient(
        base_url="https://agent-control.test",
        api_key="test-key",
        runtime_auth_mode="jwt",
        transport=transport,
    ) as client:
        with pytest.raises(RuntimeError, match="response was not an object"):
            await client.post_runtime_evaluation(
                json={"target_type": "log_stream", "target_id": "ls-1"},
                target_type="log_stream",
                target_id="ls-1",
            )


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
