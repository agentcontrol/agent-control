"""Integration tests for the runtime token exchange endpoint.

These tests cover the request shape, the runtime-secret guard, and the
end-to-end exchange-then-verify path: a token minted via
``POST /api/v1/auth/runtime-token-exchange`` is verified by
``LocalJwtVerifyProvider`` and yields a target-bound :class:`Principal`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent_control_server.auth_framework import Operation, Principal
from agent_control_server.auth_framework.core import (
    clear_authorizers,
    set_authorizer,
)
from agent_control_server.auth_framework.providers import (
    HeaderAuthProvider,
    LocalJwtVerifyProvider,
)


_TEST_SECRET = "test-runtime-secret-12345678901234567890"


class _StubExchangeAuthorizer:
    """Stand-in for HttpUpstreamAuthProvider.

    Returns a Principal with the grant fields the exchange endpoint
    needs (target binding, scopes, expiry) so the unit test can run
    without a real upstream.
    """

    def __init__(
        self,
        *,
        actor_id: str = "actor-x",
        scopes: tuple[str, ...] = ("runtime.use",),
        target_type: str | None = None,
        target_id: str | None = None,
        grant_expires_at: datetime | None = None,
    ) -> None:
        self._actor_id = actor_id
        self._scopes = scopes
        self._target_type = target_type
        self._target_id = target_id
        self._grant_expires_at = grant_expires_at
        self.calls: list[dict[str, object]] = []

    async def authorize(self, request, operation, context=None):
        self.calls.append({"operation": operation, "context": context})
        return Principal(
            namespace_key="default",
            caller_id=self._actor_id,
            target_type=self._target_type,
            target_id=self._target_id,
            scopes=self._scopes,
            grant_expires_at=self._grant_expires_at,
        )


def test_exchange_endpoint_503_when_secret_not_configured(client: TestClient):
    response = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-1"},
    )
    assert response.status_code == 503


def test_exchange_endpoint_mints_token_when_configured(client: TestClient):
    stub = _StubExchangeAuthorizer(
        actor_id="actor-9",
        scopes=("runtime.use",),
        target_type="log_stream",
        target_id="ls-42",
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    clear_authorizers()
    set_authorizer(stub)

    with patch.dict(
        "os.environ",
        {"AGENT_CONTROL_RUNTIME_TOKEN_SECRET": _TEST_SECRET},
    ):
        response = client.post(
            "/api/v1/auth/runtime-token-exchange",
            json={"target_type": "log_stream", "target_id": "ls-42"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_type"] == "log_stream"
    assert body["target_id"] == "ls-42"
    assert "runtime.use" in body["scopes"]
    assert body["token"]
    assert body["expires_at"]


def test_exchange_endpoint_rejects_target_mismatch(client: TestClient):
    """Provider says the credential is scoped to one target; body asks for another."""
    stub = _StubExchangeAuthorizer(
        target_type="log_stream",
        target_id="authorized-target",
    )
    clear_authorizers()
    set_authorizer(stub)

    with patch.dict(
        "os.environ",
        {"AGENT_CONTROL_RUNTIME_TOKEN_SECRET": _TEST_SECRET},
    ):
        response = client.post(
            "/api/v1/auth/runtime-token-exchange",
            json={"target_type": "log_stream", "target_id": "different-target"},
        )

    assert response.status_code == 400


def test_exchange_endpoint_rejects_missing_target(client: TestClient):
    response = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream"},  # target_id missing
    )
    assert response.status_code == 422


def test_exchange_endpoint_passes_target_to_authorizer_context(client: TestClient):
    stub = _StubExchangeAuthorizer()
    clear_authorizers()
    set_authorizer(stub)

    with patch.dict(
        "os.environ",
        {"AGENT_CONTROL_RUNTIME_TOKEN_SECRET": _TEST_SECRET},
    ):
        response = client.post(
            "/api/v1/auth/runtime-token-exchange",
            json={"target_type": "log_stream", "target_id": "ls-7"},
        )

    assert response.status_code == 200
    assert stub.calls
    assert stub.calls[0]["operation"] == Operation.RUNTIME_TOKEN_EXCHANGE
    assert stub.calls[0]["context"] == {
        "target_type": "log_stream",
        "target_id": "ls-7",
    }


@pytest.mark.asyncio
async def test_exchange_then_verify_full_round_trip(client: TestClient):
    """End-to-end: exchange yields a token, verify provider accepts it."""
    from unittest.mock import MagicMock

    stub = _StubExchangeAuthorizer(actor_id="actor-rt", scopes=("runtime.use",))
    clear_authorizers()
    set_authorizer(stub)

    with patch.dict(
        "os.environ",
        {"AGENT_CONTROL_RUNTIME_TOKEN_SECRET": _TEST_SECRET},
    ):
        response = client.post(
            "/api/v1/auth/runtime-token-exchange",
            json={"target_type": "log_stream", "target_id": "ls-99"},
        )
    assert response.status_code == 200, response.text
    token = response.json()["token"]

    verify_provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = MagicMock()
    request.headers = {"Authorization": f"Bearer {token}"}
    principal = await verify_provider.authorize(request, Operation.RUNTIME_USE)

    assert principal.target_type == "log_stream"
    assert principal.target_id == "ls-99"
    assert principal.caller_id == "actor-rt"


def test_exchange_endpoint_rejects_grant_without_runtime_use(client: TestClient):
    """If the upstream grant lists scopes but omits runtime.use, fail closed.

    Adding runtime.use here would mint a token with more authority than
    the upstream granted.
    """
    stub = _StubExchangeAuthorizer(scopes=("runtime.read_only",))
    clear_authorizers()
    set_authorizer(stub)

    with patch.dict(
        "os.environ",
        {"AGENT_CONTROL_RUNTIME_TOKEN_SECRET": _TEST_SECRET},
    ):
        response = client.post(
            "/api/v1/auth/runtime-token-exchange",
            json={"target_type": "log_stream", "target_id": "ls-1"},
        )
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_exchange_propagates_non_default_namespace_into_token(
    client: TestClient,
):
    """A token minted in org A must verify back into org A, not the default."""
    from unittest.mock import MagicMock

    class _OrgAuthorizer:
        async def authorize(self, request, operation, context=None):
            return Principal(
                namespace_key="org-A",
                caller_id="actor-A",
                target_type=context.get("target_type") if context else None,
                target_id=context.get("target_id") if context else None,
                scopes=("runtime.use",),
            )

    clear_authorizers()
    set_authorizer(_OrgAuthorizer())

    with patch.dict(
        "os.environ",
        {"AGENT_CONTROL_RUNTIME_TOKEN_SECRET": _TEST_SECRET},
    ):
        response = client.post(
            "/api/v1/auth/runtime-token-exchange",
            json={"target_type": "log_stream", "target_id": "ls-org-a"},
        )
    assert response.status_code == 200, response.text
    token = response.json()["token"]

    verify_provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    principal = await verify_provider.authorize(req, Operation.RUNTIME_USE)

    assert principal.namespace_key == "org-A"
    assert principal.target_id == "ls-org-a"
