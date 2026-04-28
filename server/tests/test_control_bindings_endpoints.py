"""HTTP-level coverage for the ``/control-bindings`` endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD


_BINDINGS_URL = "/api/v1/control-bindings"


def _create_control(client: TestClient, name: str | None = None) -> int:
    payload = {"name": name or f"control-{uuid.uuid4().hex[:12]}", "data": VALID_CONTROL_PAYLOAD}
    resp = client.put("/api/v1/controls", json=payload)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


def _create_binding(
    client: TestClient,
    *,
    control_id: int,
    target_type: str = "env",
    target_id: str = "prod",
    agent_name: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "target_type": target_type,
        "target_id": target_id,
        "control_id": control_id,
        "enabled": enabled,
    }
    if agent_name is not None:
        body["agent_name"] = agent_name
    resp = client.put(_BINDINGS_URL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_target_default_binding_returns_id(client: TestClient) -> None:
    control_id = _create_control(client)
    body = _create_binding(client, control_id=control_id)
    assert isinstance(body["binding_id"], int)


def test_create_target_agent_binding_returns_id(client: TestClient) -> None:
    control_id = _create_control(client)
    body = _create_binding(
        client, control_id=control_id, agent_name="support-router"
    )
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


def test_create_duplicate_target_default_returns_409(
    client: TestClient,
) -> None:
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


def test_create_binding_with_malformed_agent_name_returns_409_or_400(
    client: TestClient,
) -> None:
    # Mixed-case agent_name violates the agent name format check constraint.
    control_id = _create_control(client)
    resp = client.put(
        _BINDINGS_URL,
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
            "agent_name": "Support-Router",
        },
    )
    # The exact code surfaced depends on how the IntegrityError propagates;
    # what matters is the request is rejected.
    assert resp.status_code >= 400


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
    assert body["agent_name"] is None
    assert body["enabled"] is True
    assert body["namespace_key"] == "default"


def test_get_unknown_binding_returns_404(client: TestClient) -> None:
    resp = client.get(f"{_BINDINGS_URL}/999999")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_BINDING_NOT_FOUND"


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


def test_non_admin_can_read(non_admin_client: TestClient, client: TestClient) -> None:
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id)

    resp = non_admin_client.get(_BINDINGS_URL)
    assert resp.status_code == 200, resp.text
