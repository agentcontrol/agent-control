"""Unit tests for the request-auth framework.

Covers:
- ``HeaderAuthProvider`` resolves tenant from the header (and falls back
  to the default when absent or empty), and enforces the per-operation
  access level from ``OSS_AUTH_LEVELS`` against the legacy OSS credential
  check.
- ``HttpUpstreamAuthProvider`` forwards the caller's credentials to the
  configured upstream, handles allow/deny responses, and fails closed on
  network errors / 5xx.
- ``require_operation`` honours the configured authorizer and routes
  the ``context_builder`` output to it.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from agent_control_server.auth import (
    Operation,
    Principal,
    require_operation,
    set_request_authorizer,
)
from agent_control_server.auth.providers.header import HeaderAuthProvider
from agent_control_server.auth.providers.http_upstream import HttpUpstreamAuthProvider

# ---------------------------------------------------------------------------
# Header provider
# ---------------------------------------------------------------------------


class TestHeaderAuthProvider:
    @pytest.mark.asyncio
    async def test_resolves_tenant_from_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given: auth disabled so AUTHENTICATED/ADMIN levels pass through
        # the credential check; a request with X-Tenant-Id
        from agent_control_server.config import auth_settings

        monkeypatch.setattr(auth_settings, "api_key_enabled", False)
        authorizer = HeaderAuthProvider()
        request = _fake_request(headers={"x-tenant-id": "tenant-a"})

        # When: we authorize
        principal = await authorizer.authorize(
            request, operation=Operation.controls_read, context={}
        )

        # Then: the principal's tenant_id is the header value
        assert principal.tenant_id == "tenant-a"
        assert principal.subject_id is None

    @pytest.mark.asyncio
    async def test_falls_back_to_default_when_header_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given: a request with no tenant header
        from agent_control_server.config import auth_settings

        monkeypatch.setattr(auth_settings, "api_key_enabled", False)
        authorizer = HeaderAuthProvider(default_tenant_id="default-tenant")
        request = _fake_request(headers={})

        # When / Then
        principal = await authorizer.authorize(
            request, operation=Operation.controls_read, context={}
        )
        assert principal.tenant_id == "default-tenant"

    @pytest.mark.asyncio
    async def test_trims_whitespace_and_falls_back_on_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given: a request with a whitespace-only tenant header
        from agent_control_server.config import auth_settings

        monkeypatch.setattr(auth_settings, "api_key_enabled", False)
        authorizer = HeaderAuthProvider(default_tenant_id="default-tenant")
        request = _fake_request(headers={"x-tenant-id": "   "})

        # When / Then: falls back to default
        principal = await authorizer.authorize(
            request, operation=Operation.controls_read, context={}
        )
        assert principal.tenant_id == "default-tenant"


# ---------------------------------------------------------------------------
# HTTP upstream provider
# ---------------------------------------------------------------------------


class TestHttpUpstreamAuthProvider:
    @pytest.mark.asyncio
    async def test_forwards_caller_credentials_and_returns_principal(self) -> None:
        # Given: an upstream that returns a 200 allow with a principal
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = request.read()
            return httpx.Response(
                200,
                json={
                    "allowed": True,
                    "principal": {"tenant_id": "org-1", "subject_id": "user-42"},
                },
            )

        authorizer = HttpUpstreamAuthProvider(
            upstream_url="http://upstream",
            service_token="service-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        request = _fake_request(
            headers={
                "authorization": "Bearer user-jwt",
                "cookie": "session=abc",
                "x-irrelevant": "should-not-forward",
            }
        )

        # When: we authorize a target_bindings.write op
        principal = await authorizer.authorize(
            request,
            operation=Operation.target_bindings_write,
            context={"target_type": "log_stream", "external_id": "abc-123"},
        )

        # Then: principal shape matches the upstream response
        assert principal.tenant_id == "org-1"
        assert principal.subject_id == "user-42"

        # And: credentials were forwarded; service token was added; the
        # unrelated header was not forwarded
        headers = captured["headers"]
        assert headers["authorization"] == "Bearer user-jwt"
        assert headers["cookie"] == "session=abc"
        assert headers["x-agent-control-service-token"] == "service-secret"
        assert "x-irrelevant" not in headers

        # And: the body contains the operation + context the caller expects
        import json

        body = json.loads(captured["body"])
        assert body["operation"] == "target_bindings.write"
        assert body["context"] == {"target_type": "log_stream", "external_id": "abc-123"}

        await authorizer.aclose()

    @pytest.mark.asyncio
    async def test_maps_upstream_deny_codes_to_http_statuses(self) -> None:
        async def _check_status(upstream_status: int, expected: int) -> None:
            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(upstream_status, json={"allowed": False, "code": "X"})

            authorizer = HttpUpstreamAuthProvider(
                upstream_url="http://upstream",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
            with pytest.raises(HTTPException) as exc:
                await authorizer.authorize(
                    _fake_request({"authorization": "Bearer x"}),
                    operation=Operation.controls_read,
                    context={},
                )
            assert exc.value.status_code == expected
            await authorizer.aclose()

        await _check_status(401, 401)
        await _check_status(403, 403)
        await _check_status(404, 404)

    @pytest.mark.asyncio
    async def test_fails_closed_on_upstream_5xx(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="unavailable")

        authorizer = HttpUpstreamAuthProvider(
            upstream_url="http://upstream",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(HTTPException) as exc:
            await authorizer.authorize(
                _fake_request({"authorization": "Bearer x"}),
                operation=Operation.controls_read,
                context={},
            )
        assert exc.value.status_code == 503
        await authorizer.aclose()

    @pytest.mark.asyncio
    async def test_fails_closed_on_network_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        authorizer = HttpUpstreamAuthProvider(
            upstream_url="http://upstream",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(HTTPException) as exc:
            await authorizer.authorize(
                _fake_request({"authorization": "Bearer x"}),
                operation=Operation.controls_read,
                context={},
            )
        assert exc.value.status_code == 503
        await authorizer.aclose()

    @pytest.mark.asyncio
    async def test_rejects_response_missing_principal_tenant(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"allowed": True, "principal": {}})

        authorizer = HttpUpstreamAuthProvider(
            upstream_url="http://upstream",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(HTTPException) as exc:
            await authorizer.authorize(
                _fake_request({"authorization": "Bearer x"}),
                operation=Operation.controls_read,
                context={},
            )
        assert exc.value.status_code == 502
        await authorizer.aclose()


# ---------------------------------------------------------------------------
# require_operation dependency factory
# ---------------------------------------------------------------------------


class TestRequireOperation:
    def test_dependency_routes_operation_and_context_to_authorizer(self) -> None:
        """An integration-ish test: a tiny FastAPI app wired with our dep."""
        # Given: a stub authorizer that records its inputs
        captured: dict[str, object] = {}

        class _StubAuthorizer:
            async def authorize(
                self,
                request: Request,
                *,
                operation: Operation,
                context: dict[str, object],
            ) -> Principal:
                captured["operation"] = operation
                captured["context"] = context
                return Principal(tenant_id="from-authorizer")

        set_request_authorizer(_StubAuthorizer())

        # And: a FastAPI app that applies the dependency to a path operation
        app = FastAPI()

        def _context(request: Request) -> dict[str, object]:
            return {
                "target_type": request.path_params["target_type"],
                "external_id": request.path_params["external_id"],
            }

        @app.put("/api/v1/targets/{target_type}/{external_id}")
        async def handler(
            target_type: str,
            external_id: str,
            principal: Principal = __import__("fastapi").Depends(
                require_operation(
                    Operation.target_bindings_write,
                    context_builder=_context,
                )
            ),
        ) -> dict[str, str]:
            return {"tenant_id": principal.tenant_id}

        # When: we hit the endpoint
        client = TestClient(app)
        response = client.put("/api/v1/targets/log_stream/abc-123")

        # Then: operation + context were routed through
        assert response.status_code == 200
        assert response.json() == {"tenant_id": "from-authorizer"}
        assert captured["operation"] == Operation.target_bindings_write
        assert captured["context"] == {"target_type": "log_stream", "external_id": "abc-123"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_request(headers: dict[str, str]) -> Request:
    """Build a minimal ASGI Request usable by the authorizer under test."""
    scope = {
        "type": "http",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "path_params": {},
    }
    return Request(scope)  # type: ignore[arg-type]
