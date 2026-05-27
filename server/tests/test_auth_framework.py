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
    LocalJwtVerifyProvider,
    NoAuthProvider,
)
from agent_control_server.auth_framework.providers.header import (
    DEFAULT_OPERATION_ACCESS,
)
from agent_control_server.auth_framework.providers.http_upstream import (
    HttpUpstreamConfig,
)
from agent_control_server.config import auth_settings
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


def _clear_auth_settings_cache() -> None:
    for attr in (
        "_parsed_api_keys",
        "_parsed_admin_api_keys",
        "_all_valid_keys",
        "_all_admin_keys",
    ):
        auth_settings.__dict__.pop(attr, None)


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
# NoAuthProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_auth_provider_allows_any_operation():
    provider = NoAuthProvider(default_namespace_key="ns-local")

    principal = await provider.authorize(
        _build_request(),
        Operation.CONTROLS_DELETE,
    )

    assert principal == Principal(namespace_key="ns-local")


@pytest.mark.asyncio
async def test_no_auth_provider_grants_runtime_exchange_scope():
    provider = NoAuthProvider()

    principal = await provider.authorize(
        _build_request(),
        Operation.RUNTIME_TOKEN_EXCHANGE,
    )

    assert principal.scopes == (Operation.RUNTIME_USE.value,)


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

    with patch("agent_control_server.auth.auth_settings.api_key_enabled", False):
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
async def test_header_provider_authenticated_calls_local_validator():
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


def _patch_owned_upstream_client(monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    ssl_context = object()

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def aclose(self) -> None:
            captured["closed"] = True

    def fake_create_default_context(*, cafile: str | None = None) -> object:
        captured["cafile"] = cafile
        return ssl_context

    monkeypatch.setattr(
        "agent_control_server.auth_framework.providers.http_upstream.httpx.AsyncClient",
        FakeAsyncClient,
    )
    monkeypatch.setattr(
        "agent_control_server.auth_framework.providers.http_upstream.ssl.create_default_context",
        fake_create_default_context,
    )
    captured["ssl_context"] = ssl_context
    return captured


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

    assert principal == Principal(namespace_key="org-7", is_admin=True, caller_id="user-42")
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


def test_http_upstream_rejects_service_token_header_collision():
    with pytest.raises(ValueError, match="service_token_header"):
        HttpUpstreamConfig(
            url="https://upstream.example/check",
            service_token="shh",
            service_token_header="Authorization",
        )


def test_http_upstream_rejects_extra_forwarded_service_token_header_collision():
    with pytest.raises(ValueError, match="service_token_header"):
        HttpUpstreamConfig(
            url="https://upstream.example/check",
            service_token="shh",
            service_token_header="X-Custom-Auth",
            extra_forward_headers=("x-custom-auth",),
        )


@pytest.mark.asyncio
async def test_http_upstream_uses_ca_file_for_owned_client(monkeypatch):
    captured = _patch_owned_upstream_client(monkeypatch)

    provider = HttpUpstreamAuthProvider(
        HttpUpstreamConfig(
            url="https://upstream.example/check",
            timeout_seconds=2.5,
            ca_file="/etc/agent-control/auth-upstream-ca/ca.crt",
        )
    )

    await provider.aclose()

    assert captured["timeout"] == 2.5
    assert captured["cafile"] == "/etc/agent-control/auth-upstream-ca/ca.crt"
    assert captured["verify"] is captured["ssl_context"]
    assert captured["closed"] is True


@pytest.mark.asyncio
async def test_http_upstream_forwards_extra_headers():
    # Given: a provider configured with an extra header in its forward list
    captured: dict[str, Any] = {}

    def factory(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"namespace_key": "ns"})

    provider = _build_upstream(
        factory,
        config_overrides={"extra_forward_headers": ("X-Deployer-Auth",)},
    )

    # When: the inbound request carries the extra header
    inbound = _build_request(headers={"X-Deployer-Auth": "k_abc", "X-API-Key": "k1"})
    await provider.authorize(inbound, Operation.CONTROL_BINDINGS_READ)

    # Then: both the default and the extra header reach the upstream
    assert captured["headers"]["x-deployer-auth"] == "k_abc"
    assert captured["headers"]["x-api-key"] == "k1"


@pytest.mark.asyncio
async def test_http_upstream_default_forward_set_unchanged():
    # Given: a provider with no extra_forward_headers
    captured: dict[str, Any] = {}

    def factory(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"namespace_key": "ns"})

    provider = _build_upstream(factory)

    # When: the inbound carries an unlisted header alongside a default one
    inbound = _build_request(
        headers={"X-API-Key": "k1", "X-Deployer-Auth": "should-not-forward"}
    )
    await provider.authorize(inbound, Operation.CONTROL_BINDINGS_READ)

    # Then: only the default-set header reaches the upstream
    assert captured["headers"].get("x-api-key") == "k1"
    assert "x-deployer-auth" not in captured["headers"]


@pytest.mark.asyncio
async def test_http_upstream_extra_forward_dedupes_against_defaults():
    # Given: extra list duplicates a default header (different case)
    captured: dict[str, Any] = {}

    def factory(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"namespace_key": "ns"})

    provider = _build_upstream(
        factory,
        config_overrides={"extra_forward_headers": ("x-api-key", "Authorization")},
    )

    # When: inbound has both
    inbound = _build_request(headers={"X-API-Key": "k1", "Authorization": "Bearer t"})
    await provider.authorize(inbound, Operation.CONTROL_BINDINGS_READ)

    # Then: each header appears exactly once on the upstream request
    forwarded = captured["headers"]
    assert sum(1 for k in forwarded if k.lower() == "x-api-key") == 1
    assert sum(1 for k in forwarded if k.lower() == "authorization") == 1


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
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)


@pytest.mark.asyncio
async def test_http_upstream_fails_closed_on_5xx():
    provider = _build_upstream(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)
    assert exc_info.value.status_code == 503
    # Status is named in the detail so operators can distinguish the
    # catch-all path from the rate-limit branch below.
    assert "500" in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 422])
async def test_http_upstream_unexpected_4xx_reports_upstream_rejection(status):
    provider = _build_upstream(lambda req: httpx.Response(status, text="bad request"))

    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "AUTH_UPSTREAM_REJECTED"
    assert str(status) in exc_info.value.detail


@pytest.mark.asyncio
async def test_http_upstream_surfaces_rate_limit_distinctly():
    """Upstream 429 must surface a rate-limit-specific detail and hint."""

    def factory(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"})

    provider = _build_upstream(factory)
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)
    assert exc_info.value.status_code == 503
    assert "rate-limit" in exc_info.value.detail
    assert "Retry-After: 30" in exc_info.value.hint


@pytest.mark.asyncio
async def test_http_upstream_rate_limit_without_retry_after_header():
    """Rate-limit hint omits the Retry-After clause when the header is absent."""
    provider = _build_upstream(lambda req: httpx.Response(429))
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)
    assert exc_info.value.status_code == 503
    assert "rate-limit" in exc_info.value.detail
    assert "Retry-After" not in exc_info.value.hint


@pytest.mark.asyncio
async def test_http_upstream_fails_closed_on_network_error():
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    provider = _build_upstream(boom)
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_http_upstream_rejects_malformed_principal():
    provider = _build_upstream(lambda req: httpx.Response(200, json={"not_namespace_key": "x"}))
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_http_upstream_rejects_naive_expires_at():
    """A timezone-less ISO ``expires_at`` must fail closed at the parser.

    Comparing a naive datetime against ``datetime.now(UTC)`` later in
    the mint path raises ``TypeError`` and surfaces as a 500, so we
    reject at the boundary instead and surface a 502 alongside the rest
    of the malformed-grant fail-closed path.
    """
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={
                "namespace_key": "ns",
                "is_admin": False,
                "caller_id": "user",
                "expires_at": "2030-01-01T00:00:00",  # no tz info
            },
        )
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_WRITE)
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
        namespace_key="default",
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
        namespace_key="default",
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
        namespace_key="default",
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
        namespace_key="default",
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


def test_runtime_token_rejects_already_expired_upstream_grant():
    """``upstream_expires_at <= issued_at`` must raise instead of minting.

    Otherwise the exchange endpoint returns a 200 with an ``exp`` in the
    past, handing the caller a token that's dead on arrival.
    """
    from datetime import UTC, datetime, timedelta

    from agent_control_server.auth_framework.runtime_token import (
        UpstreamGrantExpiredError,
        mint_runtime_token,
    )

    now = datetime.now(UTC)
    expired = now - timedelta(seconds=1)
    with pytest.raises(UpstreamGrantExpiredError):
        mint_runtime_token(
            namespace_key="default",
            actor_id="x",
            target_type="t",
            target_id="i",
            scopes=("runtime.use",),
            secret=_TEST_SECRET,
            ttl_seconds=3600,
            upstream_expires_at=expired,
            now=now,
        )


def test_runtime_token_rejects_grant_expiring_at_issue_time():
    """``upstream_expires_at == issued_at`` is also unusable: zero TTL."""
    from datetime import UTC, datetime

    from agent_control_server.auth_framework.runtime_token import (
        UpstreamGrantExpiredError,
        mint_runtime_token,
    )

    now = datetime.now(UTC)
    with pytest.raises(UpstreamGrantExpiredError):
        mint_runtime_token(
            namespace_key="default",
            actor_id="x",
            target_type="t",
            target_id="i",
            scopes=("runtime.use",),
            secret=_TEST_SECRET,
            ttl_seconds=3600,
            upstream_expires_at=now,
            now=now,
        )


def test_runtime_token_rejects_naive_upstream_expires_at():
    """Naive datetimes raise ``RuntimeTokenError``, not ``TypeError``.

    The HTTP-upstream parser already rejects naive ``expires_at``
    fields, but the helper has other call sites (custom authorizers,
    tests) that can still pass one. The comparison against
    ``datetime.now(UTC)`` would otherwise raise a raw ``TypeError`` and
    surface as a 500 instead of a typed authorization error.
    """
    from datetime import datetime

    from agent_control_server.auth_framework.runtime_token import (
        RuntimeTokenError,
        mint_runtime_token,
    )

    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    with pytest.raises(RuntimeTokenError, match="timezone-aware"):
        mint_runtime_token(
            namespace_key="default",
            actor_id="x",
            target_type="t",
            target_id="i",
            scopes=("runtime.use",),
            secret=_TEST_SECRET,
            ttl_seconds=3600,
            upstream_expires_at=naive,
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"actor_id": ""}, "actor_id is required"),
        ({"target_type": ""}, "target_type is required"),
        ({"target_id": ""}, "target_id is required"),
    ],
)
def test_runtime_token_rejects_empty_required_claims(kwargs, message):
    from agent_control_server.auth_framework.runtime_token import (
        RuntimeTokenError,
        mint_runtime_token,
    )

    token_kwargs = {
        "namespace_key": "default",
        "actor_id": "actor",
        "target_type": "target",
        "target_id": "target-id",
        "scopes": ("runtime.use",),
        "secret": _TEST_SECRET,
        "ttl_seconds": 60,
    }
    token_kwargs.update(kwargs)

    with pytest.raises(RuntimeTokenError, match=message):
        mint_runtime_token(**token_kwargs)


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
        namespace_key="default",
        actor_id="actor-7",
        target_type="log_stream",
        target_id="ls-42",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": f"Bearer {token}"})

    principal = await provider.authorize(
        request,
        Operation.RUNTIME_USE,
        context={"target_type": "log_stream", "target_id": "ls-42"},
    )

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
        namespace_key="default",
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


@pytest.mark.asyncio
async def test_local_jwt_provider_carries_token_namespace_to_principal():
    """Tokens minted in a non-default namespace must verify under that namespace."""
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
    )

    token, _ = mint_runtime_token(
        namespace_key="org-7",
        actor_id="a",
        target_type="log_stream",
        target_id="ls",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": f"Bearer {token}"})

    principal = await provider.authorize(
        request,
        Operation.RUNTIME_USE,
        context={"target_type": "log_stream", "target_id": "ls"},
    )
    assert principal.namespace_key == "org-7"


@pytest.mark.asyncio
async def test_local_jwt_provider_rejects_missing_target_context():
    """A target-bound runtime token requires matching request target context."""
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
    )
    from agent_control_server.errors import ForbiddenError

    token, _ = mint_runtime_token(
        namespace_key="default",
        actor_id="a",
        target_type="log_stream",
        target_id="bound-target",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(ForbiddenError, match="target_type does not match"):
        await provider.authorize(request, Operation.RUNTIME_USE)


@pytest.mark.asyncio
async def test_local_jwt_provider_enforces_target_context_match():
    """When the dependency surfaces a target context, the provider enforces it."""
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
    )
    from agent_control_server.errors import ForbiddenError

    token, _ = mint_runtime_token(
        namespace_key="default",
        actor_id="a",
        target_type="log_stream",
        target_id="bound-target",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(ForbiddenError, match="target_id does not match"):
        await provider.authorize(
            request,
            Operation.RUNTIME_USE,
            context={
                "target_type": "log_stream",
                "target_id": "different-target",
            },
        )


@pytest.mark.asyncio
async def test_local_jwt_provider_target_context_mismatch_on_type():
    from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
    from agent_control_server.auth_framework.runtime_token import (
        mint_runtime_token,
    )
    from agent_control_server.errors import ForbiddenError

    token, _ = mint_runtime_token(
        namespace_key="default",
        actor_id="a",
        target_type="log_stream",
        target_id="ls",
        scopes=("runtime.use",),
        secret=_TEST_SECRET,
        ttl_seconds=60,
    )
    provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = _build_request(headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(ForbiddenError, match="target_type does not match"):
        await provider.authorize(
            request,
            Operation.RUNTIME_USE,
            context={"target_type": "agent_session", "target_id": "ls"},
        )


# ---------------------------------------------------------------------------
# HttpUpstreamAuthProvider strict grant parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_upstream_rejects_wrong_typed_is_admin():
    """A string ``is_admin`` must not coerce to True; fail closed (502)."""
    provider = _build_upstream(
        lambda req: httpx.Response(200, json={"namespace_key": "n", "is_admin": "false"})
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.RUNTIME_TOKEN_EXCHANGE)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_http_upstream_rejects_malformed_scopes():
    """Non-string entries in ``scopes`` should fail closed, not be silently dropped."""
    provider = _build_upstream(
        lambda req: httpx.Response(200, json={"namespace_key": "n", "scopes": ["runtime.use", 7]})
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.RUNTIME_TOKEN_EXCHANGE)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_http_upstream_rejects_malformed_expires_at():
    """A non-ISO ``expires_at`` should fail closed instead of removing the TTL cap."""
    provider = _build_upstream(
        lambda req: httpx.Response(200, json={"namespace_key": "n", "expires_at": "not a date"})
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.RUNTIME_TOKEN_EXCHANGE)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_http_upstream_rejects_non_string_target_fields():
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={
                "namespace_key": "n",
                "target_type": 1,
                "target_id": "ls",
            },
        )
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.RUNTIME_TOKEN_EXCHANGE)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_http_upstream_rejects_target_type_only_grant():
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={"namespace_key": "n", "target_type": "log_stream"},
        )
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.RUNTIME_TOKEN_EXCHANGE)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_http_upstream_rejects_target_id_only_grant():
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={"namespace_key": "n", "target_id": "ls-1"},
        )
    )
    with pytest.raises(APIError) as exc_info:
        await provider.authorize(_build_request(), Operation.RUNTIME_TOKEN_EXCHANGE)
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_http_upstream_accepts_iso_datetime_and_array_scopes():
    """Upstream wire shapes must round-trip cleanly.

    A real upstream returns ``expires_at`` as an ISO string and
    ``scopes`` as a JSON array. The strict parser must accept them both
    while still rejecting type-coercion bugs (covered by the
    is_admin/scopes tests above).
    """
    iso_expiry = "2030-01-01T00:00:00+00:00"
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={
                "namespace_key": "org-1",
                "is_admin": False,
                "scopes": ["runtime.use", "runtime.read_only"],
                "target_type": "log_stream",
                "target_id": "ls-1",
                "expires_at": iso_expiry,
            },
        )
    )
    principal = await provider.authorize(
        _build_request(),
        Operation.RUNTIME_TOKEN_EXCHANGE,
        context={"target_type": "log_stream", "target_id": "ls-1"},
    )
    assert principal.namespace_key == "org-1"
    assert principal.scopes == ("runtime.use", "runtime.read_only")
    assert principal.target_type == "log_stream"
    assert principal.target_id == "ls-1"
    assert principal.grant_expires_at is not None
    assert principal.grant_expires_at.isoformat() == iso_expiry


@pytest.mark.asyncio
async def test_http_upstream_rejects_target_grant_mismatch():
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={
                "namespace_key": "org-1",
                "target_type": "log_stream",
                "target_id": "different",
            },
        )
    )

    with pytest.raises(ForbiddenError, match="does not match"):
        await provider.authorize(
            _build_request(),
            Operation.RUNTIME_TOKEN_EXCHANGE,
            context={"target_type": "log_stream", "target_id": "requested"},
        )


@pytest.mark.asyncio
async def test_http_upstream_rejects_target_grant_without_context():
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={
                "namespace_key": "org-1",
                "target_type": "log_stream",
                "target_id": "bound",
            },
        )
    )

    with pytest.raises(ForbiddenError, match="request target is unavailable"):
        await provider.authorize(_build_request(), Operation.CONTROL_BINDINGS_READ)


@pytest.mark.asyncio
async def test_http_upstream_rejects_target_grant_with_incomplete_context():
    provider = _build_upstream(
        lambda req: httpx.Response(
            200,
            json={
                "namespace_key": "org-1",
                "target_type": "log_stream",
                "target_id": "bound",
            },
        )
    )

    with pytest.raises(ForbiddenError, match="request target is incomplete"):
        await provider.authorize(
            _build_request(),
            Operation.CONTROL_BINDINGS_READ,
            context={"target_type": "log_stream"},
        )


# ---------------------------------------------------------------------------
# configure_auth_from_env / teardown_auth lifecycle
# ---------------------------------------------------------------------------


def test_runtime_ttl_loader_rejects_non_integer(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_TOKEN_TTL_SECONDS", "abc")
    with pytest.raises(RuntimeError, match="not an integer"):
        auth_config._load_runtime_ttl_seconds()


def test_runtime_ttl_loader_rejects_non_positive(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_TOKEN_TTL_SECONDS", "0")
    with pytest.raises(RuntimeError, match="must be positive"):
        auth_config._load_runtime_ttl_seconds()


def test_runtime_ttl_loader_rejects_above_max(monkeypatch):
    """TTLs above the hard cap must fail closed at startup.

    A misconfigured TTL of weeks or years defeats the short-credential
    design; cap independent of the upstream grant ``expires_at`` so the
    guard fires even when the upstream omits an expiry.
    """
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv(
        "AGENT_CONTROL_RUNTIME_TOKEN_TTL_SECONDS",
        str(auth_config._MAX_RUNTIME_TOKEN_TTL_SECONDS + 1),
    )
    with pytest.raises(RuntimeError, match="exceeds the maximum"):
        auth_config._load_runtime_ttl_seconds()


def test_runtime_ttl_loader_accepts_max(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv(
        "AGENT_CONTROL_RUNTIME_TOKEN_TTL_SECONDS",
        str(auth_config._MAX_RUNTIME_TOKEN_TTL_SECONDS),
    )
    assert (
        auth_config._load_runtime_ttl_seconds()
        == auth_config._MAX_RUNTIME_TOKEN_TTL_SECONDS
    )


def test_build_default_provider_accepts_none_mode(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "none")

    assert isinstance(auth_config._build_default_provider(), NoAuthProvider)


def test_build_default_provider_defaults_to_none_when_api_keys_disabled(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.delenv("AGENT_CONTROL_AUTH_MODE", raising=False)
    monkeypatch.setattr(auth_settings, "api_key_enabled", False)

    assert isinstance(auth_config._build_default_provider(), NoAuthProvider)


def test_build_default_provider_rejects_explicit_api_key_without_validator(
    monkeypatch,
):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "api_key")
    monkeypatch.setattr(auth_settings, "api_key_enabled", False)

    with pytest.raises(RuntimeError, match="AGENT_CONTROL_API_KEY_ENABLED=true"):
        auth_config._build_default_provider()


def test_build_default_provider_rejects_explicit_api_key_without_keys(
    monkeypatch,
):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "api_key")
    monkeypatch.setattr(auth_settings, "api_key_enabled", True)
    monkeypatch.setattr(auth_settings, "api_keys", "")
    monkeypatch.setattr(auth_settings, "admin_api_keys", "")
    _clear_auth_settings_cache()

    with pytest.raises(RuntimeError, match="AGENT_CONTROL_API_KEYS"):
        auth_config._build_default_provider()


def test_resolve_runtime_mode_defaults_to_default_without_secret(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", raising=False)

    assert auth_config._resolve_runtime_mode() == "default"


def test_resolve_runtime_mode_defaults_to_jwt_with_secret(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", raising=False)
    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", _TEST_SECRET)

    assert auth_config._resolve_runtime_mode() == "jwt"


def test_configure_runtime_none_installs_no_auth_provider(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", "none")
    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", raising=False)

    auth_config.configure_auth_from_env()

    assert isinstance(get_authorizer(Operation.RUNTIME_USE), NoAuthProvider)
    assert auth_config.runtime_auth_config() is None


def test_configure_runtime_api_key_ignores_jwt_secret(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", "api_key")
    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", _TEST_SECRET)

    auth_config.configure_auth_from_env()

    assert isinstance(get_authorizer(Operation.RUNTIME_USE), HeaderAuthProvider)
    assert auth_config.runtime_auth_config() is None


def test_configure_runtime_api_key_rejects_without_validator(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", "api_key")
    monkeypatch.setattr(auth_settings, "api_key_enabled", False)

    with pytest.raises(RuntimeError, match="AGENT_CONTROL_RUNTIME_AUTH_MODE=api_key"):
        auth_config.configure_auth_from_env()


def test_configure_runtime_unset_preserves_no_auth_default(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "none")
    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", raising=False)

    auth_config.configure_auth_from_env()

    assert isinstance(get_authorizer(Operation.RUNTIME_USE), NoAuthProvider)
    assert auth_config.runtime_auth_config() is None


@pytest.mark.asyncio
async def test_configure_runtime_unset_preserves_http_upstream_default(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "http_upstream")
    monkeypatch.setenv("AGENT_CONTROL_AUTH_UPSTREAM_URL", "https://auth.example.test/check")
    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", raising=False)

    try:
        auth_config.configure_auth_from_env()

        default_provider = get_authorizer(Operation.CONTROLS_READ)
        runtime_provider = get_authorizer(Operation.RUNTIME_USE)
        assert isinstance(default_provider, HttpUpstreamAuthProvider)
        assert runtime_provider is default_provider
        assert auth_config.runtime_auth_config() is None
    finally:
        await auth_config.teardown_auth()


@pytest.mark.asyncio
async def test_configure_http_upstream_management_with_jwt_runtime(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "http_upstream")
    monkeypatch.setenv("AGENT_CONTROL_AUTH_UPSTREAM_URL", "https://auth.example.test/check")
    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", "jwt")
    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", _TEST_SECRET)

    try:
        auth_config.configure_auth_from_env()

        assert isinstance(get_authorizer(Operation.CONTROLS_READ), HttpUpstreamAuthProvider)
        assert isinstance(get_authorizer(Operation.RUNTIME_USE), LocalJwtVerifyProvider)
        runtime_config = auth_config.runtime_auth_config()
        assert runtime_config is not None
        assert runtime_config.secret == _TEST_SECRET
    finally:
        await auth_config.teardown_auth()


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, ()),
        ("", ()),
        ("   ", ()),
        ("X-One", ("X-One",)),
        ("X-One,X-Two", ("X-One", "X-Two")),
        ("  X-One  ,  X-Two  ", ("X-One", "X-Two")),
        ("X-One,,X-Two", ("X-One", "X-Two")),
        ("X-One,x-one,X-One", ("X-One",)),
        ("X-A,X-B,x-a,X-C,X-b", ("X-A", "X-B", "X-C")),
    ],
)
def test_parse_extra_forward_headers(raw, expected):
    from agent_control_server.auth_framework.config import _parse_extra_forward_headers

    assert _parse_extra_forward_headers(raw) == expected


@pytest.mark.asyncio
async def test_configure_http_upstream_extra_forward_headers_env(monkeypatch):
    """Setting the env var threads extra_forward_headers into the provider."""
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "http_upstream")
    monkeypatch.setenv("AGENT_CONTROL_AUTH_UPSTREAM_URL", "https://auth.example.test/check")
    monkeypatch.setenv(
        "AGENT_CONTROL_AUTH_UPSTREAM_EXTRA_FORWARD_HEADERS",
        "X-Deployer-Auth, X-Deployer-Trace",
    )

    try:
        auth_config.configure_auth_from_env()
        provider = get_authorizer(Operation.CONTROLS_READ)
        assert isinstance(provider, HttpUpstreamAuthProvider)
        assert provider._config.extra_forward_headers == (
            "X-Deployer-Auth",
            "X-Deployer-Trace",
        )
    finally:
        await auth_config.teardown_auth()


@pytest.mark.asyncio
async def test_configure_http_upstream_ca_file_env(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    clear_authorizers()
    captured = _patch_owned_upstream_client(monkeypatch)

    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "http_upstream")
    monkeypatch.setenv("AGENT_CONTROL_AUTH_UPSTREAM_URL", "https://auth.example.test/check")
    monkeypatch.setenv(
        "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE",
        " /etc/agent-control/auth-upstream-ca/ca.crt ",
    )

    try:
        auth_config.configure_auth_from_env()
        provider = get_authorizer(Operation.CONTROLS_READ)
        assert isinstance(provider, HttpUpstreamAuthProvider)
        assert provider._config.ca_file == "/etc/agent-control/auth-upstream-ca/ca.crt"
        assert captured["cafile"] == "/etc/agent-control/auth-upstream-ca/ca.crt"
        assert captured["verify"] is captured["ssl_context"]
    finally:
        await auth_config.teardown_auth()


@pytest.mark.asyncio
async def test_configure_http_upstream_ca_file_env_reports_bad_path(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    def fake_create_default_context(*, cafile: str | None = None) -> object:
        raise FileNotFoundError(cafile or "")

    clear_authorizers()
    monkeypatch.setattr(
        "agent_control_server.auth_framework.providers.http_upstream.ssl.create_default_context",
        fake_create_default_context,
    )
    monkeypatch.setenv("AGENT_CONTROL_AUTH_MODE", "http_upstream")
    monkeypatch.setenv("AGENT_CONTROL_AUTH_UPSTREAM_URL", "https://auth.example.test/check")
    monkeypatch.setenv(
        "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE",
        "/etc/agent-control/auth-upstream-ca/missing-ca.crt",
    )

    try:
        with pytest.raises(
            RuntimeError,
            match=r"AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE=.*missing-ca\.crt.*not found or unreadable",
        ):
            auth_config.configure_auth_from_env()
    finally:
        await auth_config.teardown_auth()


def test_configure_runtime_jwt_requires_secret(monkeypatch):
    from agent_control_server.auth_framework import config as auth_config

    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_AUTH_MODE", "jwt")
    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="requires AGENT_CONTROL_RUNTIME_TOKEN_SECRET"):
        auth_config.configure_auth_from_env()


def test_configure_then_reconfigure_clears_runtime_override(monkeypatch):
    """Reconfiguring without a runtime secret must drop the override."""
    from agent_control_server.auth_framework import config as auth_config
    from agent_control_server.auth_framework.providers import (
        LocalJwtVerifyProvider,
    )

    clear_authorizers()

    monkeypatch.setenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", _TEST_SECRET)
    auth_config.configure_auth_from_env()
    assert isinstance(get_authorizer(Operation.RUNTIME_USE), LocalJwtVerifyProvider)

    monkeypatch.delenv("AGENT_CONTROL_RUNTIME_TOKEN_SECRET", raising=False)
    auth_config.configure_auth_from_env()

    runtime_authorizer = get_authorizer(Operation.RUNTIME_USE)
    assert not isinstance(runtime_authorizer, LocalJwtVerifyProvider)


@pytest.mark.asyncio
async def test_teardown_auth_clears_registry():
    """After teardown, the registry must be empty (default + overrides)."""
    from agent_control_server.auth_framework import config as auth_config
    from agent_control_server.auth_framework.core import _operation_authorizers

    clear_authorizers()
    set_authorizer(HeaderAuthProvider())
    set_authorizer(
        HeaderAuthProvider(),
        operation=Operation.CONTROL_BINDINGS_WRITE,
    )

    auth_config._active_providers.clear()
    auth_config._active_providers.extend([HeaderAuthProvider(), HeaderAuthProvider()])

    await auth_config.teardown_auth()

    assert not auth_config._active_providers
    assert not _operation_authorizers
    with pytest.raises(RuntimeError, match="No RequestAuthorizer"):
        get_authorizer(Operation.CONTROL_BINDINGS_WRITE)
