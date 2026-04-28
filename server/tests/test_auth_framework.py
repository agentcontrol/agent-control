"""Unit tests for the pluggable request-auth framework."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_control_server.auth_framework.core import (
    Operation,
    Principal,
    get_authorizer,
    require_operation,
    set_authorizer,
)
from agent_control_server.auth_framework.providers import (
    HeaderAuthProvider,
    HttpUpstreamAuthProvider,
    OssAccessLevel,
)
from agent_control_server.auth_framework.providers.header import OSS_OPERATION_ACCESS
from agent_control_server.auth_framework.providers.http_upstream import (
    HttpUpstreamConfig,
)
from agent_control_server.errors import (
    APIError,
    AuthenticationError,
    ForbiddenError,
    NotFoundError,
)
from agent_control_server.models import DEFAULT_NAMESPACE_KEY


def _build_request(
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
):
    """Build a minimal Starlette-compatible request mock."""
    request = MagicMock()
    request.headers = headers or {}
    request.cookies = cookies or {}
    return request


# ---------------------------------------------------------------------------
# Coverage of operation -> access-level mapping
# ---------------------------------------------------------------------------


def test_oss_operation_access_covers_every_operation():
    """Every Operation member must declare an OSS access level."""
    missing = [op for op in Operation if op not in OSS_OPERATION_ACCESS]
    assert not missing, f"Operations missing OSS access mapping: {missing}"


# ---------------------------------------------------------------------------
# HeaderAuthProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_provider_public_returns_default_namespace():
    provider = HeaderAuthProvider(
        operation_access={Operation.CONTROL_BINDINGS_READ: OssAccessLevel.PUBLIC}
    )
    principal = await provider.authorize(
        _build_request(),
        Operation.CONTROL_BINDINGS_READ,
    )
    assert principal == Principal(namespace_key=DEFAULT_NAMESPACE_KEY)


@pytest.mark.asyncio
async def test_header_provider_authenticated_calls_legacy_validator():
    provider = HeaderAuthProvider()
    expected_client = MagicMock(is_admin=False, key_id="abc12345")

    with patch(
        "agent_control_server.auth_framework.providers.header._validate_api_key",
        new=AsyncMock(return_value=expected_client),
    ) as mocked:
        principal = await provider.authorize(
            _build_request(headers={"X-API-Key": "key-123"}),
            Operation.CONTROL_BINDINGS_READ,
        )

    mocked.assert_awaited_once()
    args, kwargs = mocked.await_args
    assert args[0] == "key-123"
    assert kwargs["require_admin"] is False
    assert principal.namespace_key == DEFAULT_NAMESPACE_KEY
    assert principal.is_admin is False
    assert principal.caller_id == "abc12345"


@pytest.mark.asyncio
async def test_header_provider_admin_op_requires_admin():
    provider = HeaderAuthProvider()
    admin_client = MagicMock(is_admin=True, key_id="admin01")

    with patch(
        "agent_control_server.auth_framework.providers.header._validate_api_key",
        new=AsyncMock(return_value=admin_client),
    ) as mocked:
        principal = await provider.authorize(
            _build_request(headers={"X-API-Key": "admin-key"}),
            Operation.CONTROL_BINDINGS_WRITE,
        )

    args, kwargs = mocked.await_args
    assert kwargs["require_admin"] is True
    assert principal.is_admin is True


@pytest.mark.asyncio
async def test_header_provider_v1_ignores_namespace_header():
    """V1 always returns the default namespace regardless of header value."""
    provider = HeaderAuthProvider(
        operation_access={Operation.CONTROL_BINDINGS_READ: OssAccessLevel.PUBLIC}
    )
    principal = await provider.authorize(
        _build_request(headers={"X-Namespace-Key": "org-foo"}),
        Operation.CONTROL_BINDINGS_READ,
    )
    assert principal.namespace_key == DEFAULT_NAMESPACE_KEY


@pytest.mark.asyncio
async def test_header_provider_unknown_operation_raises():
    provider = HeaderAuthProvider(operation_access={})
    with pytest.raises(RuntimeError, match="No OSS access level"):
        await provider.authorize(
            _build_request(),
            Operation.CONTROL_BINDINGS_READ,
        )


# ---------------------------------------------------------------------------
# HttpUpstreamAuthProvider
# ---------------------------------------------------------------------------


def _build_upstream(
    response_factory,
    *,
    config_overrides: dict[str, Any] | None = None,
) -> HttpUpstreamAuthProvider:
    config_kwargs: dict[str, Any] = {"url": "https://upstream.example/check"}
    if config_overrides:
        config_kwargs.update(config_overrides)
    config = HttpUpstreamConfig(**config_kwargs)

    transport = httpx.MockTransport(response_factory)
    client = httpx.AsyncClient(transport=transport)
    return HttpUpstreamAuthProvider(config, client=client)


@pytest.mark.asyncio
async def test_http_upstream_returns_principal_on_200():
    captured: dict[str, Any] = {}

    def factory(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "namespace_key": "org-7",
                "is_admin": True,
                "caller_id": "user-42",
            },
        )

    provider = _build_upstream(factory)
    request = _build_request(headers={"X-API-Key": "caller-key"})
    principal = await provider.authorize(request, Operation.CONTROL_BINDINGS_WRITE)

    assert principal == Principal(
        namespace_key="org-7", is_admin=True, caller_id="user-42"
    )
    assert captured["url"] == "https://upstream.example/check"
    assert captured["headers"]["x-api-key"] == "caller-key"


@pytest.mark.asyncio
async def test_http_upstream_forwards_service_token():
    captured: dict[str, Any] = {}

    def factory(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"namespace_key": "ns"})

    provider = _build_upstream(
        factory,
        config_overrides={
            "service_token": "shh",
            "service_token_header": "X-Custom-Token",
        },
    )
    await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_READ)

    assert captured["headers"]["x-custom-token"] == "shh"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected",
    [
        (401, AuthenticationError),
        (403, ForbiddenError),
        (404, NotFoundError),
    ],
)
async def test_http_upstream_maps_client_errors(status, expected):
    provider = _build_upstream(lambda req: httpx.Response(status))
    with pytest.raises(expected):
        await provider.authorize(
            _build_request(), Operation.CONTROL_BINDINGS_WRITE
        )


@pytest.mark.asyncio
async def test_http_upstream_fails_closed_on_5xx():
    provider = _build_upstream(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(
            _build_request(), Operation.CONTROL_BINDINGS_WRITE
        )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_http_upstream_fails_closed_on_network_error():
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    provider = _build_upstream(boom)
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(
            _build_request(), Operation.CONTROL_BINDINGS_WRITE
        )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_http_upstream_rejects_malformed_principal():
    provider = _build_upstream(
        lambda req: httpx.Response(200, json={"not_namespace_key": "x"})
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(
            _build_request(), Operation.CONTROL_BINDINGS_WRITE
        )
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# require_operation factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_operation_routes_to_installed_authorizer():
    seen: dict[str, Any] = {}

    class _Recording:
        async def authorize(self, request, operation, context=None):
            seen["op"] = operation
            seen["context"] = context
            return Principal(namespace_key="ns", is_admin=False)

    set_authorizer(_Recording())
    try:
        dep = require_operation(
            Operation.CONTROL_BINDINGS_WRITE,
            context_builder=lambda r: {"k": "v"},
        )
        principal = await dep(_build_request())
    finally:
        set_authorizer(HeaderAuthProvider())

    assert seen == {
        "op": Operation.CONTROL_BINDINGS_WRITE,
        "context": {"k": "v"},
    }
    assert principal.namespace_key == "ns"


@pytest.mark.asyncio
async def test_get_authorizer_raises_when_unset():
    set_authorizer(None)
    try:
        with pytest.raises(RuntimeError, match="No RequestAuthorizer"):
            get_authorizer()
    finally:
        set_authorizer(HeaderAuthProvider())
