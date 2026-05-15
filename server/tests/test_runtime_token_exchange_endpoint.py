"""Integration tests for the runtime token exchange endpoint.

These tests cover the request shape, the runtime-secret guard, and the
end-to-end exchange-then-verify path: a token minted via
``POST /api/v1/auth/runtime-token-exchange`` is verified by
``LocalJwtVerifyProvider`` and yields a target-bound :class:`Principal`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent_control_server.auth_framework import Operation, Principal
from agent_control_server.auth_framework.config import (
    RuntimeAuthConfig,
    set_runtime_auth_config,
)
from agent_control_server.auth_framework.core import (
    clear_authorizers,
    set_authorizer,
)
from agent_control_server.auth_framework.providers import (
    LocalJwtVerifyProvider,
)

_TEST_SECRET = "test-runtime-secret-12345678901234567890"


@pytest.fixture
def runtime_config_enabled():
    """Install a deterministic runtime-auth config for the test, then clear."""
    set_runtime_auth_config(RuntimeAuthConfig(secret=_TEST_SECRET, ttl_seconds=300))
    try:
        yield
    finally:
        set_runtime_auth_config(None)


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


def test_exchange_endpoint_mints_token_when_configured(client: TestClient, runtime_config_enabled):
    stub = _StubExchangeAuthorizer(
        actor_id="actor-9",
        scopes=("runtime.use",),
        target_type="log_stream",
        target_id="ls-42",
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    clear_authorizers()
    set_authorizer(stub)

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


def test_exchange_audit_log_redacts_actor_id(
    client: TestClient,
    runtime_config_enabled,
    caplog: pytest.LogCaptureFixture,
):
    stub = _StubExchangeAuthorizer(
        actor_id="user@example.test",
        scopes=("runtime.use",),
        target_type="log_stream",
        target_id="ls-42",
    )
    clear_authorizers()
    set_authorizer(stub)

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/api/v1/auth/runtime-token-exchange",
            json={"target_type": "log_stream", "target_id": "ls-42"},
        )

    assert response.status_code == 200, response.text
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Runtime token exchanged"
    ]
    assert records
    record = records[-1]
    assert "actor_id" not in record.__dict__
    assert record.__dict__["actor_id_hash"]


def test_exchange_endpoint_rejects_target_mismatch(client: TestClient, runtime_config_enabled):
    """Provider says the credential is scoped to one target; body asks for another."""
    stub = _StubExchangeAuthorizer(
        target_type="log_stream",
        target_id="authorized-target",
    )
    clear_authorizers()
    set_authorizer(stub)

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


def test_exchange_endpoint_passes_target_to_authorizer_context(
    client: TestClient, runtime_config_enabled
):
    stub = _StubExchangeAuthorizer()
    clear_authorizers()
    set_authorizer(stub)

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
async def test_exchange_then_verify_full_round_trip(client: TestClient, runtime_config_enabled):
    """End-to-end: exchange yields a token, verify provider accepts it."""
    from unittest.mock import MagicMock

    stub = _StubExchangeAuthorizer(actor_id="actor-rt", scopes=("runtime.use",))
    clear_authorizers()
    set_authorizer(stub)

    response = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-99"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["token"]

    verify_provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    request = MagicMock()
    request.headers = {"Authorization": f"Bearer {token}"}
    principal = await verify_provider.authorize(
        request,
        Operation.RUNTIME_USE,
        context={"target_type": "log_stream", "target_id": "ls-99"},
    )

    assert principal.target_type == "log_stream"
    assert principal.target_id == "ls-99"
    assert principal.caller_id == "actor-rt"


def test_evaluation_rejects_runtime_jwt_for_wrong_target(
    client: TestClient,
    runtime_config_enabled,
):
    """A runtime JWT minted for one target cannot be used for another target."""
    stub = _StubExchangeAuthorizer(actor_id="actor-rt", scopes=("runtime.use",))
    clear_authorizers()
    set_authorizer(stub)
    set_authorizer(LocalJwtVerifyProvider(secret=_TEST_SECRET), operation=Operation.RUNTIME_USE)

    exchange = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-allowed"},
    )
    assert exchange.status_code == 200, exchange.text
    token = exchange.json()["token"]

    response = client.post(
        "/api/v1/evaluation",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_name": "agent",
            "step": {"type": "llm", "name": "step", "input": "hello"},
            "stage": "pre",
            "target_type": "log_stream",
            "target_id": "ls-other",
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Runtime token target_id does not match the request."


def test_evaluation_rejects_runtime_jwt_without_bound_target_context(
    client: TestClient,
    runtime_config_enabled,
):
    """A target-bound runtime JWT must not authorize a target-less evaluation."""
    stub = _StubExchangeAuthorizer(actor_id="actor-rt", scopes=("runtime.use",))
    clear_authorizers()
    set_authorizer(stub)
    set_authorizer(LocalJwtVerifyProvider(secret=_TEST_SECRET), operation=Operation.RUNTIME_USE)

    exchange = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-allowed"},
    )
    assert exchange.status_code == 200, exchange.text
    token = exchange.json()["token"]

    response = client.post(
        "/api/v1/evaluation",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_name": "agent",
            "step": {"type": "llm", "name": "step", "input": "hello"},
            "stage": "pre",
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Runtime token target_type does not match the request."


def test_exchange_endpoint_502_when_upstream_grant_already_expired(
    client: TestClient,
    runtime_config_enabled,
):
    """Upstream returned a grant whose expires_at is in the past.

    Without this, the endpoint mints a 200 with an already-expired
    token. The endpoint must distinguish "upstream returned bad data"
    (502) from "server misconfigured" (503).
    """
    stub = _StubExchangeAuthorizer(
        actor_id="actor-9",
        scopes=("runtime.use",),
        target_type="log_stream",
        target_id="ls-42",
        grant_expires_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    clear_authorizers()
    set_authorizer(stub)

    response = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-42"},
    )

    assert response.status_code == 502, response.text
    # Detail is sanitized at the response boundary by the error handler;
    # the 502 (vs 503 for misconfigured server) is the public contract,
    # the original "already-expired" message is preserved in server logs
    # for operators.


def test_exchange_endpoint_rejects_grant_without_runtime_use(
    client: TestClient, runtime_config_enabled
):
    """If the upstream grant lists scopes but omits runtime.use, fail closed.

    Adding runtime.use here would mint a token with more authority than
    the upstream granted.
    """
    stub = _StubExchangeAuthorizer(scopes=("runtime.read_only",))
    clear_authorizers()
    set_authorizer(stub)

    response = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-1"},
    )
    assert response.status_code == 400, response.text


def test_exchange_endpoint_rejects_explicit_empty_grant_scopes(
    client: TestClient,
    runtime_config_enabled,
):
    """An upstream that returns an explicit empty scopes array must not
    be silently upgraded to runtime.use.

    The exchange endpoint always requires the authorizer to surface
    runtime.use; an explicit empty grant is a privilege denial and must
    fail closed.
    """
    stub = _StubExchangeAuthorizer(scopes=())
    clear_authorizers()
    set_authorizer(stub)

    response = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-1"},
    )
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_exchange_propagates_non_default_namespace_into_token(
    client: TestClient,
    runtime_config_enabled,
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

    response = client.post(
        "/api/v1/auth/runtime-token-exchange",
        json={"target_type": "log_stream", "target_id": "ls-org-a"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["token"]

    verify_provider = LocalJwtVerifyProvider(secret=_TEST_SECRET)
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    principal = await verify_provider.authorize(
        req,
        Operation.RUNTIME_USE,
        context={"target_type": "log_stream", "target_id": "ls-org-a"},
    )

    assert principal.namespace_key == "org-A"
    assert principal.target_id == "ls-org-a"
