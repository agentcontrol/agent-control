"""HTTP-level coverage for the ``/control-bindings`` endpoints."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from agent_control_models.errors import ErrorCode, ErrorReason
from fastapi.testclient import TestClient
from httpx import Response

from agent_control_server.auth_framework import Operation, Principal, set_authorizer
from agent_control_server.auth_framework.providers import (
    HeaderAuthProvider,
    HttpUpstreamAuthProvider,
)
from agent_control_server.auth_framework.providers.http_upstream import HttpUpstreamConfig
from agent_control_server.errors import APIError, ForbiddenError, NotFoundError
from agent_control_server.models import DEFAULT_NAMESPACE_KEY

from .utils import VALID_CONTROL_PAYLOAD

_BINDINGS_URL = "/api/v1/control-bindings"


def _create_control(client: TestClient, name: str | None = None) -> int:
    payload = {
        "name": name or f"control-{uuid.uuid4().hex[:12]}",
        "data": VALID_CONTROL_PAYLOAD,
    }
    resp = client.put("/api/v1/controls", json=payload)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


def _create_binding(
    client: TestClient,
    *,
    control_id: int,
    target_type: str = "env",
    target_id: str = "prod",
    enabled: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "target_type": target_type,
        "target_id": target_id,
        "control_id": control_id,
        "enabled": enabled,
    }
    resp = client.put(_BINDINGS_URL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_binding_returns_id(client: TestClient) -> None:
    control_id = _create_control(client)
    body = _create_binding(client, control_id=control_id)
    assert isinstance(body["binding_id"], int)


def test_create_binding_with_unknown_control_returns_404(
    client: TestClient,
) -> None:
    resp = client.put(
        _BINDINGS_URL,
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": 999_999,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_create_duplicate_binding_returns_409(client: TestClient) -> None:
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id)
    resp = client.put(
        _BINDINGS_URL,
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_BINDING_CONFLICT"


def test_get_binding_returns_full_payload(client: TestClient) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]

    resp = client.get(f"{_BINDINGS_URL}/{binding_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == binding_id
    assert body["control_id"] == control_id
    assert body["target_type"] == "env"
    assert body["target_id"] == "prod"
    assert body["enabled"] is True
    assert body["namespace_key"] == "default"


def test_get_unknown_binding_returns_404(client: TestClient) -> None:
    resp = client.get(f"{_BINDINGS_URL}/999999")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_BINDING_NOT_FOUND"


def test_binding_id_routes_authorize_the_stored_target(client: TestClient) -> None:
    # Given a binding whose opaque target is stored only in the database.
    control_id = _create_control(client)
    binding_id = _create_binding(
        client,
        control_id=control_id,
        target_type="custom_target",
        target_id="target-42",
    )["binding_id"]
    calls: list[tuple[str, Operation, dict[str, Any] | None]] = []

    class RecordingAuthorizer:
        binding_target_authorization = True

        async def resolve_identity(self, request: Any, operation: Operation) -> Principal:
            del request
            calls.append(("identity", operation, None))
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request
            calls.append(("authorize", operation, context))
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(RecordingAuthorizer())

    # When each by-ID route is called without target data in the request.
    get_resp = client.get(f"{_BINDINGS_URL}/{binding_id}")
    patch_resp = client.patch(f"{_BINDINGS_URL}/{binding_id}", json={"enabled": False})
    delete_resp = client.delete(f"{_BINDINGS_URL}/{binding_id}")

    # Then every authorization call receives the target stored on the binding.
    assert get_resp.status_code == 200, get_resp.text
    assert patch_resp.status_code == 200, patch_resp.text
    assert delete_resp.status_code == 200, delete_resp.text
    target_context = {"target_type": "custom_target", "target_id": "target-42"}
    assert calls == [
        ("identity", Operation.CONTROL_BINDINGS_READ, None),
        ("authorize", Operation.CONTROL_BINDINGS_READ, target_context),
        ("identity", Operation.CONTROL_BINDINGS_WRITE, None),
        ("authorize", Operation.CONTROL_BINDINGS_WRITE, target_context),
        ("identity", Operation.CONTROL_BINDINGS_WRITE, None),
        ("authorize", Operation.CONTROL_BINDINGS_WRITE, target_context),
    ]


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
@pytest.mark.parametrize("exists", [True, False])
@pytest.mark.parametrize(
    ("api_key", "expected_error_code"),
    [(None, "AUTH_MISSING_KEY"), ("wrong-key", "AUTH_INVALID_KEY")],
)
def test_binding_id_routes_preserve_authentication_errors(
    method: str,
    exists: bool,
    api_key: str | None,
    expected_error_code: str,
    client: TestClient,
    app: object,
) -> None:
    # Given: a caller with no valid credential and an existing or missing ID.
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]
    headers = {} if api_key is None else {"X-API-Key": api_key}
    unauthorized_client = TestClient(app, raise_server_exceptions=True, headers=headers)

    # When: the caller accesses the binding by ID.
    url = f"{_BINDINGS_URL}/{binding_id if exists else 999_999}"
    if method == "get":
        response = unauthorized_client.get(url)
    elif method == "patch":
        response = unauthorized_client.patch(url, json={"enabled": False})
    else:
        response = unauthorized_client.delete(url)

    # Then: the route preserves the normal 401 challenge.
    assert response.status_code == 401
    assert response.json()["error_code"] == expected_error_code
    assert response.headers["WWW-Authenticate"] == "ApiKey"


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_binding_id_write_checks_local_access_before_lookup(
    method: str, non_admin_client: TestClient
) -> None:
    # Given: a valid non-admin key and a missing binding ID.
    url = f"{_BINDINGS_URL}/999999"

    # When: the caller attempts an ID-based write.
    if method == "patch":
        response = non_admin_client.patch(url, json={"enabled": False})
    else:
        response = non_admin_client.delete(url)

    # Then: the operation-wide access check preserves the normal 403.
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_binding_id_lookup_is_scoped_before_target_authorization(
    method: str, client: TestClient
) -> None:
    class NamespaceAuthorizer:
        binding_target_authorization = True
        namespace_key = "other-namespace"

        def __init__(self) -> None:
            self.target_calls = 0

        async def resolve_identity(self, request: Any, operation: Operation) -> Principal:
            del request, operation
            return Principal(namespace_key=self.namespace_key, is_admin=True)

        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request, operation, context
            self.target_calls += 1
            return Principal(namespace_key=self.namespace_key, is_admin=True)

    # Given: a binding in another namespace and an identity in the default namespace.
    authorizer = NamespaceAuthorizer()
    set_authorizer(authorizer)
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]
    authorizer.namespace_key = DEFAULT_NAMESPACE_KEY
    authorizer.target_calls = 0

    # When: the caller tries the foreign ID and a missing ID.
    def request_id(requested_id: int) -> Response:
        url = f"{_BINDINGS_URL}/{requested_id}"
        if method == "get":
            return client.get(url)
        if method == "patch":
            return client.patch(url, json={"enabled": False})
        return client.delete(url)

    foreign = request_id(binding_id)
    missing = request_id(999_999)

    # Then: neither ID reaches target authorization or mutates the binding.
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error_code"] == missing.json()["error_code"] == (
        "CONTROL_BINDING_NOT_FOUND"
    )
    assert authorizer.target_calls == 0
    authorizer.namespace_key = "other-namespace"
    stored = client.get(f"{_BINDINGS_URL}/{binding_id}")
    assert stored.status_code == 200
    assert stored.json()["enabled"] is True


def test_binding_id_identity_failure_does_not_depend_on_id(
    client: TestClient,
) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]

    class UnavailableAuthorizer:
        binding_target_authorization = True

        async def resolve_identity(self, request: Any, operation: Operation) -> Principal:
            del request, operation
            raise APIError(
                status_code=503,
                error_code=ErrorCode.AUTH_MISCONFIGURED,
                reason=ErrorReason.SERVICE_UNAVAILABLE,
                detail="Authorization service unavailable.",
            )

        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            raise AssertionError("Target authorization must not run after identity failure")

    # Given: the identity service is unavailable before any binding lookup.
    set_authorizer(UnavailableAuthorizer())

    # When: the caller requests an existing and a missing ID.
    existing = client.get(f"{_BINDINGS_URL}/{binding_id}")
    missing = client.get(f"{_BINDINGS_URL}/999999")

    # Then: both fail with the same upstream error.
    assert existing.status_code == missing.status_code == 503
    assert existing.json()["error_code"] == missing.json()["error_code"] == "AUTH_MISCONFIGURED"


@pytest.mark.parametrize("denial", ["forbidden", "not_found"])
def test_binding_id_target_denial_looks_like_missing_binding(
    denial: str, client: TestClient
) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]

    class DenyingAuthorizer:
        binding_target_authorization = True

        async def resolve_identity(self, request: Any, operation: Operation) -> Principal:
            del request, operation
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY)

        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request, operation, context
            if denial == "forbidden":
                raise ForbiddenError(
                    error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                    detail="Target access denied.",
                )
            raise NotFoundError(
                error_code=ErrorCode.AUTH_INVALID_KEY,
                detail="Target not found.",
                resource="Target",
            )

    # Given: an identity in the binding's namespace without target access.
    set_authorizer(DenyingAuthorizer())

    # When: the caller requests the denied binding and a missing ID.
    denied = client.get(f"{_BINDINGS_URL}/{binding_id}")
    missing = client.get(f"{_BINDINGS_URL}/999999")

    # Then: both use the binding-not-found response contract.
    assert denied.status_code == missing.status_code == 404
    assert denied.json()["error_code"] == missing.json()["error_code"] == (
        "CONTROL_BINDING_NOT_FOUND"
    )


def test_binding_id_legacy_authorizer_preserves_namespace_wide_check(client: TestClient) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]
    contexts: list[dict[str, Any] | None] = []

    class LegacyAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request, operation
            contexts.append(context)
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY)

    # Given: a provider that implements the original authorize-only contract.
    set_authorizer(LegacyAuthorizer())

    # When: an ID-based binding read succeeds.
    response = client.get(f"{_BINDINGS_URL}/{binding_id}")

    # Then: the legacy provider receives the same single targetless check as before.
    assert response.status_code == 200
    assert contexts == [None]


@pytest.mark.parametrize(
    ("method", "operation"),
    [
        ("get", Operation.CONTROL_BINDINGS_READ),
        ("patch", Operation.CONTROL_BINDINGS_WRITE),
        ("delete", Operation.CONTROL_BINDINGS_WRITE),
    ],
)
@pytest.mark.parametrize(
    ("namespace_key", "expected_status"),
    [(DEFAULT_NAMESPACE_KEY, 200), ("other-namespace", 404)],
)
def test_binding_id_non_orbit_http_upstream_preserves_targetless_check(
    method: str,
    operation: Operation,
    namespace_key: str,
    expected_status: int,
    client: TestClient,
) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]
    upstream_requests: list[httpx.Request] = []

    def upstream_auth(request: httpx.Request) -> Response:
        upstream_requests.append(request)
        if "context" in json.loads(request.content):
            # This upstream accepted the old namespace-wide contract only.
            return Response(400, json={"detail": "Unexpected target context"})
        return Response(200, json={"namespace_key": namespace_key})

    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_auth))
    set_authorizer(
        HttpUpstreamAuthProvider(
            HttpUpstreamConfig(url="https://custom.example/check"),
            client=upstream_client,
        )
    )

    url = f"{_BINDINGS_URL}/{binding_id}"
    if method == "get":
        response = client.get(url)
    elif method == "patch":
        response = client.patch(url, json={"enabled": False})
    else:
        response = client.delete(url)

    assert response.status_code == expected_status, response.text
    assert len(upstream_requests) == 1
    assert str(upstream_requests[0].url) == "https://custom.example/check"
    assert upstream_requests[0].method == "POST"
    assert upstream_requests[0].headers["x-api-key"] == client.headers["x-api-key"]
    assert json.loads(upstream_requests[0].content) == {"operation": operation.value}
    if expected_status == 404:
        assert response.json()["error_code"] == "CONTROL_BINDING_NOT_FOUND"
    elif method == "get":
        assert response.json()["namespace_key"] == DEFAULT_NAMESPACE_KEY
    else:
        assert response.json()["success"] is True

    set_authorizer(HeaderAuthProvider())
    stored = client.get(url)
    if method == "delete" and expected_status == 200:
        assert stored.status_code == 404
    else:
        assert stored.status_code == 200
        assert stored.json()["enabled"] is (method != "patch" or expected_status != 200)


def test_binding_id_orbit_http_upstream_authorizes_stored_target(client: TestClient) -> None:
    # Given: Orbit requires target context for management authorization.
    control_id = _create_control(client)
    target_id = str(uuid.uuid4())
    binding_id = _create_binding(
        client, control_id=control_id, target_type="log_stream", target_id=target_id
    )["binding_id"]
    upstream_requests: list[httpx.Request] = []

    def upstream_auth(request: httpx.Request) -> Response:
        upstream_requests.append(request)
        if request.url.path == "/internal/auth/resolve_tenant_context":
            return Response(200, json={"namespace_key": DEFAULT_NAMESPACE_KEY})
        body = json.loads(request.content)
        if body.get("context") != {"target_type": "log_stream", "target_id": target_id}:
            return Response(400, json={"detail": "Target context required"})
        return Response(200, json={"namespace_key": DEFAULT_NAMESPACE_KEY})

    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_auth))
    set_authorizer(
        HttpUpstreamAuthProvider(
            HttpUpstreamConfig(
                url="https://orbit.example/internal/auth/agent_control/check_management_access",
                identity_url="https://orbit.example/internal/auth/resolve_tenant_context",
            ),
            client=upstream_client,
        )
    )

    # When: an ID-based delete is requested without a target in the request.
    response = client.delete(f"{_BINDINGS_URL}/{binding_id}")

    # Then: identity resolution precedes a target-bound management check.
    assert response.status_code == 200, response.text
    assert [request.url.path for request in upstream_requests] == [
        "/internal/auth/resolve_tenant_context",
        "/internal/auth/agent_control/check_management_access",
    ]
    assert json.loads(upstream_requests[1].content) == {
        "operation": Operation.CONTROL_BINDINGS_WRITE.value,
        "context": {"target_type": "log_stream", "target_id": target_id},
    }


def test_binding_id_delete_rechecks_the_authorized_namespace(
    client: TestClient,
) -> None:
    # Given a binding in the default namespace and an authorizer resolving another one.
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]
    authorized_namespace = "other-namespace"

    class NamespaceAuthorizer:
        binding_target_authorization = True

        async def resolve_identity(self, request: Any, operation: Operation) -> Principal:
            del request, operation
            return Principal(namespace_key=authorized_namespace, is_admin=True)

        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request, operation, context
            return Principal(namespace_key=authorized_namespace, is_admin=True)

    set_authorizer(NamespaceAuthorizer())

    # When deletion is authorized for a namespace that does not own the row.
    delete_resp = client.delete(f"{_BINDINGS_URL}/{binding_id}")

    # Then the scoped mutation is rejected and the original binding remains.
    assert delete_resp.status_code == 404
    authorized_namespace = DEFAULT_NAMESPACE_KEY
    get_resp = client.get(f"{_BINDINGS_URL}/{binding_id}")
    assert get_resp.status_code == 200, get_resp.text


def test_binding_id_patch_rechecks_the_authorized_namespace(
    client: TestClient,
) -> None:
    # Given a binding in the default namespace and an authorizer resolving another one.
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]
    authorized_namespace = "other-namespace"

    class NamespaceAuthorizer:
        binding_target_authorization = True

        async def resolve_identity(self, request: Any, operation: Operation) -> Principal:
            del request, operation
            return Principal(namespace_key=authorized_namespace, is_admin=True)

        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request, operation, context
            return Principal(namespace_key=authorized_namespace, is_admin=True)

    set_authorizer(NamespaceAuthorizer())

    # When an update is authorized for a namespace that does not own the row.
    patch_resp = client.patch(
        f"{_BINDINGS_URL}/{binding_id}",
        json={"enabled": False},
    )

    # Then the scoped mutation is rejected and the original binding remains enabled.
    assert patch_resp.status_code == 404
    authorized_namespace = DEFAULT_NAMESPACE_KEY
    get_resp = client.get(f"{_BINDINGS_URL}/{binding_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["enabled"] is True


def test_binding_id_path_validation_runs_before_authorization(
    client: TestClient,
) -> None:
    # Given an authorizer that records every invocation.
    calls: list[Operation] = []

    class RecordingAuthorizer:
        binding_target_authorization = True

        async def resolve_identity(self, request: Any, operation: Operation) -> Principal:
            del request
            calls.append(operation)
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request, context
            calls.append(operation)
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(RecordingAuthorizer())

    # When a caller supplies a non-integer binding ID.
    resp = client.get(f"{_BINDINGS_URL}/not-an-integer")

    # Then FastAPI reports validation without loading or authorizing a binding.
    assert resp.status_code == 422
    assert calls == []


def test_list_bindings_returns_all(client: TestClient) -> None:
    control_id = _create_control(client)
    _create_binding(
        client, control_id=control_id, target_type="env", target_id="prod"
    )
    _create_binding(
        client, control_id=control_id, target_type="env", target_id="dev"
    )

    resp = client.get(_BINDINGS_URL)
    assert resp.status_code == 200, resp.text
    bindings = resp.json()["bindings"]
    assert {b["target_id"] for b in bindings if b["control_id"] == control_id} == {
        "prod",
        "dev",
    }


def test_list_bindings_returns_pagination_metadata(client: TestClient) -> None:
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id, target_id="prod")
    _create_binding(client, control_id=control_id, target_id="dev")

    resp = client.get(_BINDINGS_URL, params={"limit": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["bindings"]) == 1
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["next_cursor"] is not None
    assert body["pagination"]["limit"] == 1
    assert body["pagination"]["total"] == 2


def test_list_bindings_cursor_walks_pages(client: TestClient) -> None:
    control_id = _create_control(client)
    first_id = _create_binding(client, control_id=control_id, target_id="prod")[
        "binding_id"
    ]
    second_id = _create_binding(client, control_id=control_id, target_id="dev")[
        "binding_id"
    ]

    page_one = client.get(_BINDINGS_URL, params={"limit": 1}).json()
    cursor = page_one["pagination"]["next_cursor"]
    assert cursor is not None

    page_two = client.get(
        _BINDINGS_URL, params={"limit": 1, "cursor": cursor}
    ).json()

    page_one_ids = [b["id"] for b in page_one["bindings"]]
    page_two_ids = [b["id"] for b in page_two["bindings"]]
    # Cursor walks newest-first; the first page returns the most recent
    # binding, the second page returns the older one.
    assert {*page_one_ids, *page_two_ids} == {first_id, second_id}
    assert page_two["pagination"]["has_more"] is False


def test_list_bindings_with_target_filter(client: TestClient) -> None:
    control_id = _create_control(client)
    _create_binding(
        client, control_id=control_id, target_type="env", target_id="prod"
    )
    _create_binding(
        client, control_id=control_id, target_type="env", target_id="dev"
    )

    resp = client.get(
        _BINDINGS_URL, params={"target_type": "env", "target_id": "prod"}
    )
    assert resp.status_code == 200, resp.text
    target_ids = [b["target_id"] for b in resp.json()["bindings"]]
    assert target_ids == ["prod"]


def test_patch_binding_toggles_enabled(client: TestClient) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]

    resp = client.patch(
        f"{_BINDINGS_URL}/{binding_id}", json={"enabled": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"success": True, "enabled": False}

    fetched = client.get(f"{_BINDINGS_URL}/{binding_id}").json()
    assert fetched["enabled"] is False


def test_patch_binding_updates_updated_at(client: TestClient) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]

    initial = client.get(f"{_BINDINGS_URL}/{binding_id}").json()
    initial_updated_at = initial["updated_at"]

    resp = client.patch(
        f"{_BINDINGS_URL}/{binding_id}", json={"enabled": False}
    )
    assert resp.status_code == 200, resp.text

    after_patch = client.get(f"{_BINDINGS_URL}/{binding_id}").json()
    assert after_patch["updated_at"] != initial_updated_at


def test_patch_unknown_binding_returns_404(client: TestClient) -> None:
    resp = client.patch(
        f"{_BINDINGS_URL}/999999", json={"enabled": False}
    )
    assert resp.status_code == 404


def test_delete_binding_removes_it(client: TestClient) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]

    resp = client.delete(f"{_BINDINGS_URL}/{binding_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"success": True}

    follow_up = client.get(f"{_BINDINGS_URL}/{binding_id}")
    assert follow_up.status_code == 404


def test_delete_unknown_binding_returns_404(client: TestClient) -> None:
    resp = client.delete(f"{_BINDINGS_URL}/999999")
    assert resp.status_code == 404


def test_non_admin_cannot_write(non_admin_client: TestClient, client: TestClient) -> None:
    control_id = _create_control(client)

    create_resp = non_admin_client.put(
        _BINDINGS_URL,
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
        },
    )
    assert create_resp.status_code == 403

    binding_id = _create_binding(client, control_id=control_id)["binding_id"]

    patch_resp = non_admin_client.patch(
        f"{_BINDINGS_URL}/{binding_id}", json={"enabled": False}
    )
    assert patch_resp.status_code == 403

    delete_resp = non_admin_client.delete(f"{_BINDINGS_URL}/{binding_id}")
    assert delete_resp.status_code == 403

    unchanged = client.get(f"{_BINDINGS_URL}/{binding_id}")
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["enabled"] is True


def test_non_admin_can_read(non_admin_client: TestClient, client: TestClient) -> None:
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id)

    resp = non_admin_client.get(_BINDINGS_URL)
    assert resp.status_code == 200, resp.text


# Natural-key (idempotent) endpoints.


def test_upsert_by_key_creates_new_binding(client: TestClient) -> None:
    control_id = _create_control(client)
    body = {
        "target_type": "env",
        "target_id": "prod",
        "control_id": control_id,
        "enabled": True,
    }
    resp = client.put(f"{_BINDINGS_URL}/by-key", json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["created"] is True
    assert payload["enabled"] is True
    assert isinstance(payload["binding_id"], int)


def test_upsert_by_key_is_idempotent_and_updates_enabled(
    client: TestClient,
) -> None:
    control_id = _create_control(client)
    body = {
        "target_type": "env",
        "target_id": "prod",
        "control_id": control_id,
        "enabled": True,
    }
    first = client.put(f"{_BINDINGS_URL}/by-key", json=body).json()
    second = client.put(
        f"{_BINDINGS_URL}/by-key", json={**body, "enabled": False}
    ).json()

    assert second["created"] is False
    assert second["enabled"] is False
    assert second["binding_id"] == first["binding_id"]


def test_upsert_by_key_updates_updated_at_on_existing_row(
    client: TestClient,
) -> None:
    control_id = _create_control(client)
    body = {
        "target_type": "env",
        "target_id": "prod",
        "control_id": control_id,
        "enabled": True,
    }
    first_id = client.put(f"{_BINDINGS_URL}/by-key", json=body).json()["binding_id"]
    initial = client.get(f"{_BINDINGS_URL}/{first_id}").json()
    initial_updated_at = initial["updated_at"]

    client.put(f"{_BINDINGS_URL}/by-key", json={**body, "enabled": False}).json()
    after_upsert = client.get(f"{_BINDINGS_URL}/{first_id}").json()
    assert after_upsert["updated_at"] != initial_updated_at


def test_patch_by_key_updates_existing_binding(client: TestClient) -> None:
    control_id = _create_control(client)
    binding_id = _create_binding(client, control_id=control_id)["binding_id"]
    body = {
        "target_type": "env",
        "target_id": "prod",
        "control_id": control_id,
        "enabled": False,
    }

    resp = client.patch(f"{_BINDINGS_URL}/by-key", json=body)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"success": True, "enabled": False}
    fetched = client.get(f"{_BINDINGS_URL}/{binding_id}").json()
    assert fetched["enabled"] is False


def test_patch_by_key_returns_404_without_creating_binding(client: TestClient) -> None:
    control_id = _create_control(client)
    body = {
        "target_type": "env",
        "target_id": "prod",
        "control_id": control_id,
        "enabled": False,
    }

    resp = client.patch(f"{_BINDINGS_URL}/by-key", json=body)

    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_BINDING_NOT_FOUND"
    bindings = client.get(
        _BINDINGS_URL,
        params={"target_type": "env", "target_id": "prod", "control_id": control_id},
    ).json()["bindings"]
    assert bindings == []


def test_patch_by_key_passes_target_context_to_authorizer(
    client: TestClient,
) -> None:
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id)
    calls: list[tuple[Operation, dict[str, Any] | None]] = []

    class RecordingAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            del request
            calls.append((operation, context))
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(RecordingAuthorizer())

    resp = client.patch(
        f"{_BINDINGS_URL}/by-key",
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
            "enabled": False,
        },
    )

    assert resp.status_code == 200, resp.text
    assert calls == [
        (
            Operation.CONTROL_BINDINGS_WRITE,
            {"target_type": "env", "target_id": "prod"},
        )
    ]


def test_delete_by_key_removes_existing_binding(client: TestClient) -> None:
    control_id = _create_control(client)
    client.put(
        f"{_BINDINGS_URL}/by-key",
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
        },
    )
    resp = client.post(
        f"{_BINDINGS_URL}/by-key:delete",
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}


def test_delete_by_key_is_idempotent_when_missing(client: TestClient) -> None:
    control_id = _create_control(client)
    resp = client.post(
        f"{_BINDINGS_URL}/by-key:delete",
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": False}


def test_non_admin_cannot_use_by_key_endpoints(
    non_admin_client: TestClient, client: TestClient
) -> None:
    control_id = _create_control(client)
    body = {
        "target_type": "env",
        "target_id": "prod",
        "control_id": control_id,
    }
    upsert_resp = non_admin_client.put(f"{_BINDINGS_URL}/by-key", json=body)
    assert upsert_resp.status_code == 403

    patch_resp = non_admin_client.patch(
        f"{_BINDINGS_URL}/by-key", json={**body, "enabled": False}
    )
    assert patch_resp.status_code == 403

    delete_resp = non_admin_client.post(
        f"{_BINDINGS_URL}/by-key:delete", json=body
    )
    assert delete_resp.status_code == 403
