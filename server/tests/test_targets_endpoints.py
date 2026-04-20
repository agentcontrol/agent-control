"""Endpoint tests for target management APIs."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD

API_PREFIX = "/api/v1"
TENANT_HEADER = "X-Tenant-Id"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _create_control(client: TestClient) -> int:
    """Create a control via the standard endpoint and return its ID."""
    resp = client.put(
        f"{API_PREFIX}/controls",
        json={"name": _unique("ctrl"), "data": VALID_CONTROL_PAYLOAD},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


def _create_target(
    client: TestClient,
    *,
    target_type: str = "environment",
    external_id: str | None = None,
    name: str | None = None,
    data: dict | None = None,
    tenant: str | None = None,
) -> int:
    """Create a target via the API and return its ID."""
    body: dict[str, object] = {
        "target_type": target_type,
        "external_id": external_id or _unique("ext"),
    }
    if name is not None:
        body["name"] = name
    if data is not None:
        body["data"] = data
    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.post(f"{API_PREFIX}/targets", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return int(resp.json()["target_id"])


# ---------------------------------------------------------------------------
# Create / list / get / delete
# ---------------------------------------------------------------------------


def test_create_target_happy_path(client: TestClient) -> None:
    external_id = _unique("ls")
    resp = client.post(
        f"{API_PREFIX}/targets",
        json={
            "target_type": "environment",
            "external_id": external_id,
            "name": "production",
            "data": {"foo": "bar"},
        },
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert isinstance(payload["target_id"], int)

    get_resp = client.get(f"{API_PREFIX}/targets/{payload['target_id']}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["target_type"] == "environment"
    assert body["external_id"] == external_id
    assert body["name"] == "production"
    assert body["tenant_id"] == "default-tenant"
    assert body["data"] == {"foo": "bar"}


def test_create_target_rejects_duplicate_external_id_per_tenant(
    client: TestClient,
) -> None:
    external_id = _unique("ls")
    first = client.post(
        f"{API_PREFIX}/targets",
        json={"target_type": "environment", "external_id": external_id},
    )
    assert first.status_code == 201
    second = client.post(
        f"{API_PREFIX}/targets",
        json={"target_type": "environment", "external_id": external_id},
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "TARGET_CONFLICT"


def test_same_external_id_allowed_across_tenants(client: TestClient) -> None:
    external_id = _unique("ls")
    first = client.post(
        f"{API_PREFIX}/targets",
        json={"target_type": "environment", "external_id": external_id},
        headers={TENANT_HEADER: "tenant-a"},
    )
    second = client.post(
        f"{API_PREFIX}/targets",
        json={"target_type": "environment", "external_id": external_id},
        headers={TENANT_HEADER: "tenant-b"},
    )
    assert first.status_code == 201
    assert second.status_code == 201


def test_list_targets_filters_by_tenant(client: TestClient) -> None:
    _create_target(client, tenant="tenant-a")
    _create_target(client, tenant="tenant-a")
    _create_target(client, tenant="tenant-b")

    resp_a = client.get(
        f"{API_PREFIX}/targets", headers={TENANT_HEADER: "tenant-a"}
    )
    assert resp_a.status_code == 200
    assert len(resp_a.json()["targets"]) == 2

    resp_b = client.get(
        f"{API_PREFIX}/targets", headers={TENANT_HEADER: "tenant-b"}
    )
    assert len(resp_b.json()["targets"]) == 1


def test_list_targets_filters_by_target_type(client: TestClient) -> None:
    _create_target(client, target_type="environment")
    _create_target(client, target_type="dataset")
    resp = client.get(f"{API_PREFIX}/targets", params={"target_type": "environment"})
    assert resp.status_code == 200
    returned_types = {t["target_type"] for t in resp.json()["targets"]}
    assert returned_types == {"environment"}


def test_get_target_cross_tenant_returns_404(client: TestClient) -> None:
    target_id = _create_target(client, tenant="tenant-a")
    resp = client.get(
        f"{API_PREFIX}/targets/{target_id}",
        headers={TENANT_HEADER: "tenant-b"},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TARGET_NOT_FOUND"


def test_delete_target_happy_path(client: TestClient) -> None:
    target_id = _create_target(client)
    resp = client.delete(f"{API_PREFIX}/targets/{target_id}")
    assert resp.status_code == 204
    get_resp = client.get(f"{API_PREFIX}/targets/{target_id}")
    assert get_resp.status_code == 404


def test_delete_target_not_found(client: TestClient) -> None:
    resp = client.delete(f"{API_PREFIX}/targets/999999")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TARGET_NOT_FOUND"


# ---------------------------------------------------------------------------
# Attach / detach / toggle target_controls
# ---------------------------------------------------------------------------


def test_attach_control_to_target(client: TestClient) -> None:
    target_id = _create_target(client)
    control_id = _create_control(client)
    resp = client.post(
        f"{API_PREFIX}/targets/{target_id}/controls/{control_id}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control_id"] == control_id
    assert body["enabled"] is True


def test_attach_control_with_enabled_false(client: TestClient) -> None:
    target_id = _create_target(client)
    control_id = _create_control(client)
    resp = client.post(
        f"{API_PREFIX}/targets/{target_id}/controls/{control_id}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_attach_control_is_idempotent(client: TestClient) -> None:
    target_id = _create_target(client)
    control_id = _create_control(client)
    first = client.post(f"{API_PREFIX}/targets/{target_id}/controls/{control_id}")
    second = client.post(f"{API_PREFIX}/targets/{target_id}/controls/{control_id}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_attach_control_target_not_found(client: TestClient) -> None:
    control_id = _create_control(client)
    resp = client.post(f"{API_PREFIX}/targets/999999/controls/{control_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TARGET_NOT_FOUND"


def test_attach_control_control_not_found(client: TestClient) -> None:
    target_id = _create_target(client)
    resp = client.post(f"{API_PREFIX}/targets/{target_id}/controls/999999")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_detach_control(client: TestClient) -> None:
    target_id = _create_target(client)
    control_id = _create_control(client)
    client.post(f"{API_PREFIX}/targets/{target_id}/controls/{control_id}")
    resp = client.delete(f"{API_PREFIX}/targets/{target_id}/controls/{control_id}")
    assert resp.status_code == 204


def test_detach_control_not_attached(client: TestClient) -> None:
    target_id = _create_target(client)
    control_id = _create_control(client)
    resp = client.delete(f"{API_PREFIX}/targets/{target_id}/controls/{control_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TARGET_CONTROL_NOT_FOUND"


def test_toggle_enabled(client: TestClient) -> None:
    target_id = _create_target(client)
    control_id = _create_control(client)
    client.post(f"{API_PREFIX}/targets/{target_id}/controls/{control_id}")
    resp = client.patch(
        f"{API_PREFIX}/targets/{target_id}/controls/{control_id}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_toggle_missing_attachment_returns_404(client: TestClient) -> None:
    target_id = _create_target(client)
    control_id = _create_control(client)
    resp = client.patch(
        f"{API_PREFIX}/targets/{target_id}/controls/{control_id}",
        json={"enabled": False},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TARGET_CONTROL_NOT_FOUND"


def test_list_target_controls(client: TestClient) -> None:
    target_id = _create_target(client)
    control_a = _create_control(client)
    control_b = _create_control(client)
    client.post(f"{API_PREFIX}/targets/{target_id}/controls/{control_a}")
    client.post(
        f"{API_PREFIX}/targets/{target_id}/controls/{control_b}",
        json={"enabled": False},
    )

    resp = client.get(f"{API_PREFIX}/targets/{target_id}/controls")
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_id"] == target_id
    returned = {(c["control_id"], c["enabled"]) for c in body["controls"]}
    assert returned == {(control_a, True), (control_b, False)}


# ---------------------------------------------------------------------------
# Tenant header handling
# ---------------------------------------------------------------------------


def test_missing_tenant_header_falls_back_to_default_tenant(client: TestClient) -> None:
    target_id = _create_target(client)
    resp = client.get(f"{API_PREFIX}/targets/{target_id}")
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "default-tenant"


def test_whitespace_tenant_header_treated_as_default(client: TestClient) -> None:
    target_id = _create_target(client, tenant="   ")
    resp = client.get(f"{API_PREFIX}/targets/{target_id}")
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "default-tenant"


@pytest.mark.parametrize("missing_admin", [True])
def test_create_target_requires_admin_key(
    missing_admin: bool, non_admin_client: TestClient
) -> None:
    """Creation requires admin; a plain API key is rejected."""
    resp = non_admin_client.post(
        f"{API_PREFIX}/targets",
        json={"target_type": "environment", "external_id": _unique("ls")},
    )
    assert resp.status_code == 403
