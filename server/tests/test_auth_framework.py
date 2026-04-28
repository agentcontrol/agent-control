"""Unit tests for the pluggable request-auth framework."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_control_server.auth_framework.core import (
    Operation,
    Principal,
    clear_authorizers,
    get_authorizer,
    require_operation,
    set_authorizer,
)
from agent_control_server.auth_framework.providers import (
    AccessLevel,
    HeaderAuthProvider,
    HttpUpstreamAuthProvider,
)
from agent_control_server.auth_framework.providers.header import (
    DEFAULT_OPERATION_ACCESS,
)
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


# 32-byte test secret (HS256 wants >= 32 bytes; shorter raises a warning).
_TEST_SECRET = "test-runtime-secret-12345678901234567890"
_OTHER_SECRET = "other-runtime-secret-1234567890123456789"


# ---------------------------------------------------------------------------
# Coverage of operation -> access-level mapping
# ---------------------------------------------------------------------------


def test_default_operation_access_covers_every_operation():
    """Every Operation member must declare a default access level."""
    missing = [op for op in Operation if op not in DEFAULT_OPERATION_ACCESS]
    assert not missing, f"Operations missing default access mapping: {missing}"


# ---------------------------------------------------------------------------
# HeaderAuthProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_provider_no_auth_mode_passes_admin_op():
    """When ``api_key_enabled`` is False, even admin operations succeed.

    Preserves the pre-framework behavior where setting the server into
    no-auth mode opens every endpoint regardless of access level.
    """
    provider = HeaderAuthProvider()

    with patch(
        "agent_control_server.auth.auth_settings.api_key_enabled", False
    ):
        principal = await provider.authorize(
            _build_request(),
            Operation.CONTROL_BINDINGS_WRITE,
        )

    assert principal.namespace_key == DEFAULT_NAMESPACE_KEY
    assert principal.is_admin is False


@pytest.mark.asyncio
async def test_header_provider_public_returns_default_namespace():
    provider = HeaderAuthProvider(
        operation_access={Operation.CONTROL_BINDINGS_READ: AccessLevel.PUBLIC}
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
        operation_access={Operation.CONTROL_BINDINGS_READ: AccessLevel.PUBLIC}
    )
    principal = await provider.authorize(
        _build_request(headers={"X-Namespace-Key": "org-foo"}),
        Operation.CONTROL_BINDINGS_READ,
    )
    assert principal.namespace_key == DEFAULT_NAMESPACE_KEY


@pytest.mark.asyncio
async def test_header_provider_unknown_operation_raises():
    provider = HeaderAuthProvider(operation_access={})
    with pytest.raises(RuntimeError, match="No access level"):
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


# ---------------------------------------------------------------------------
# Per-operation authorizer overrides
# ---------------------------------------------------------------------------


class _StubAuthorizer:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[Operation] = []

    async def authorize(self, request, operation, context=None):
        self.calls.append(operation)
        return Principal(namespace_key=f"ns-{self.label}")


def test_set_authorizer_with_operation_overrides_default():
    clear_authorizers()
    default = _StubAuthorizer("default")
    runtime = _StubAuthorizer("runtime")
    set_authorizer(default)
    set_authorizer(runtime, operation=Operation.RUNTIME_USE)

    assert get_authorizer(Operation.CONTROL_BINDINGS_WRITE) is default
    assert get_authorizer(Operation.RUNTIME_USE) is runtime


def test_set_authorizer_clear_override_falls_back_to_default():
    clear_authorizers()
    default = _StubAuthorizer("default")
    runtime = _StubAuthorizer("runtime")
    set_authorizer(default)
    set_authorizer(runtime, operation=Operation.RUNTIME_USE)
    set_authorizer(None, operation=Operation.RUNTIME_USE)

    assert get_authorizer(Operation.RUNTIME_USE) is default


@pytest.mark.asyncio
async def test_require_operation_routes_through_per_operation_override():
    clear_authorizers()
    default = _StubAuthorizer("default")
    runtime = _StubAuthorizer("runtime")
    set_authorizer(default)
    set_authorizer(runtime, operation=Operation.RUNTIME_USE)

    await require_operation(Operation.CONTROL_BINDINGS_READ)(_build_request())
    await require_operation(Operation.RUNTIME_USE)(_build_request())

    assert default.calls == [Operation.CONTROL_BINDINGS_READ]
    assert runtime.calls == [Operation.RUNTIME_USE]


# ---------------------------------------------------------------------------
# Runtime token mint / verify
# ---------------------------------------------------------------------------


def test_runtime_token_round_trips():
    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
        verify_runtime_token,
    )

    token, claims = mint_runtime_token(
        actor_id="actor-1",
        target_type="log_stream",
        target_id="ls-9",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    decoded = verify_runtime_token(token, _TEST_SECRET)
    assert decoded.actor_id == claims.actor_id
    assert decoded.target_type == "log_stream"
    assert decoded.target_id == "ls-9"
    assert decoded.scopes == ("runtime.use",)


def test_runtime_token_rejects_wrong_secret():
    from agent_control_server.auth_framework.runtime_token import (
        RuntimeTokenError,
        mint_runtime_token,
        verify_runtime_token,
    )

    token, _ = mint_runtime_token(
        actor_id="x",
        target_type="t",
        target_id="i",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    with pytest.raises(RuntimeTokenError):
        verify_runtime_token(token, _OTHER_SECRET)


def test_runtime_token_rejects_expired():
    from datetime import UTC, datetime, timedelta

    from agent_control_server.auth_framework.runtime_token import (
        RuntimeTokenError,
        mint_runtime_token,
        verify_runtime_token,
    )

    past = datetime.now(UTC) - timedelta(hours=1)
    token, _ = mint_runtime_token(
        actor_id="x",
        target_type="t",
        target_id="i",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=1,
        now=past,
    )
    with pytest.raises(RuntimeTokenError, match="expired"):
        verify_runtime_token(token, _TEST_SECRET)


def test_runtime_token_caps_ttl_at_upstream_grant():
    from datetime import UTC, datetime, timedelta

    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
    )

    now = datetime.now(UTC)
    grant_expires = now + timedelta(seconds=5)
    _, claims = mint_runtime_token(
        actor_id="x",
        target_type="t",
        target_id="i",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=3600,
        upstream_expires_at=grant_expires,
        now=now,
    )
    assert claims.expires_at == grant_expires


def test_runtime_token_rejects_management_token_passed_to_runtime_verify():
    """A token without ``domain=runtime`` must be rejected by runtime verify."""
    import jwt

    from agent_control_server.auth_framework.runtime_token import (
        RuntimeTokenError,
        verify_runtime_token,
    )

    bad = jwt.encode(
        {
            "iss": "agent-control/server",
            "domain": "management",
            "iat": 0,
            "exp": 9_999_999_999,
        },
        _TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(RuntimeTokenError, match="not a runtime token"):
        verify_runtime_token(bad, _TEST_SECRET)


# ---------------------------------------------------------------------------
# LocalJwtVerifyProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_jwt_provider_returns_target_bound_principal():
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
    )

    token, _ = mint_runtime_token(
        actor_id="actor-7",
        target_type="log_stream",
        target_id="ls-42",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": f"Bearer {token}"})

    principal = await provider.authorize(request, Operation.RUNTIME_USE)

    assert principal.target_type == "log_stream"
    assert principal.target_id == "ls-42"
    assert principal.caller_id == "actor-7"
    assert principal.scopes == ("runtime.use",)


@pytest.mark.asyncio
async def test_local_jwt_provider_missing_token_raises_401():
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.errors import AuthenticationError

    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    with pytest.raises(AuthenticationError):
        await provider.authorize(_build_request(), Operation.RUNTIME_USE)


@pytest.mark.asyncio
async def test_local_jwt_provider_wrong_scope_raises_403():
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
    )
    from agent_control_server.errors import ForbiddenError

    token, _ = mint_runtime_token(
        actor_id="x",
        target_type="t",
        target_id="i",
        scopes=("runtime.read_only",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(ForbiddenError):
        await provider.authorize(request, Operation.RUNTIME_USE)


@pytest.mark.asyncio
async def test_local_jwt_provider_rejects_non_bearer_authorization():
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.errors import AuthenticationError

    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": "Basic abc"})
    with pytest.raises(AuthenticationError):
        await provider.authorize(request, Operation.RUNTIME_USE)
