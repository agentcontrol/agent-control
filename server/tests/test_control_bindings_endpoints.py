"""HTTP-level coverage for the ``/control-bindings`` endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from agent_control_server.auth_framework import Operation, Principal, set_authorizer
from agent_control_server.models import DEFAULT_NAMESPACE_KEY
from fastapi.testclient import TestClient

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
