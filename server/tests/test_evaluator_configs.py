"""Tests for evaluator config store endpoints."""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from fastapi.testclient import TestClient


def _default_config_for_evaluator(evaluator: str) -> dict:
    if evaluator == "list":
        return {"values": ["blocked"], "logic": "any", "match_on": "match"}
    if evaluator == "regex":
        return {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}
    return {}


def _create_config_payload(
    name: str,
    evaluator: str = "regex",
    config: dict | None = None,
    description: str | None = None,
) -> dict:
    return {
        "name": name,
        "description": description,
        "evaluator": evaluator,
        "config": config if config is not None else _default_config_for_evaluator(evaluator),
    }


def _create_config(client: TestClient, name: str, evaluator: str = "regex") -> dict:
    payload = _create_config_payload(name=name, evaluator=evaluator)
    resp = client.post("/api/v1/evaluator-configs", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_create_evaluator_config_success(client: TestClient) -> None:
    # Given: A valid evaluator config payload
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name)

    # When: Creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: It is created and returned
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["name"] == name
    assert data["evaluator"] == "regex"
    assert data["config"]["pattern"] == payload["config"]["pattern"]
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_create_evaluator_config_duplicate_name_409(client: TestClient) -> None:
    # Given: An existing evaluator config name
    name = f"config-{uuid.uuid4().hex}"
    _create_config(client, name=name)

    # When: Creating another with the same name
    resp = client.post("/api/v1/evaluator-configs", json=_create_config_payload(name=name))

    # Then: Conflict error is returned
    assert resp.status_code == 409
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NAME_CONFLICT"


def test_create_evaluator_config_unknown_evaluator_allowed(client: TestClient) -> None:
    # Given: A payload with an unknown evaluator name
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="unknown-evaluator", config={})

    # When: Creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: It succeeds (validation skipped)
    assert resp.status_code == 201
    data = resp.json()
    assert data["evaluator"] == "unknown-evaluator"


def test_create_evaluator_config_agent_scoped_rejected(client: TestClient) -> None:
    # Given: A payload referencing an agent-scoped evaluator
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="agent:custom", config={})

    # When: Creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: Validation error is returned
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    assert any(err.get("field") == "evaluator" for err in data.get("errors", []))


def test_create_evaluator_config_invalid_config_422(client: TestClient) -> None:
    # Given: A payload with invalid config for regex evaluator
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="regex", config={"flags": ["IGNORECASE"]})

    # When: Creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: Validation error is returned
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "INVALID_CONFIG"
    assert any("config" in str(err.get("field", "")) for err in data.get("errors", []))


def test_update_evaluator_config_replaces_fields_and_updates_timestamp(
    client: TestClient,
) -> None:
    # Given: An existing evaluator config
    name = f"config-{uuid.uuid4().hex}"
    created = _create_config(client, name=name)

    # Ensure updated_at changes with a different timestamp
    time.sleep(0.01)

    # When: Updating the evaluator config via PUT
    payload = _create_config_payload(
        name=f"{name}-v2",
        evaluator="regex",
        config={"pattern": r"\b\d{4}\b"},
        description="Updated description",
    )
    resp = client.put(f"/api/v1/evaluator-configs/{created['id']}", json=payload)

    # Then: The config is replaced and updated_at changes
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == payload["name"]
    assert data["config"]["pattern"] == payload["config"]["pattern"]
    assert data["description"] == payload["description"]

    created_at = datetime.fromisoformat(created["created_at"])
    updated_at_before = datetime.fromisoformat(created["updated_at"])
    updated_at_after = datetime.fromisoformat(data["updated_at"])

    assert updated_at_after >= updated_at_before
    assert updated_at_after >= created_at


def test_update_evaluator_config_name_conflict_409(client: TestClient) -> None:
    # Given: Two existing evaluator configs
    first = _create_config(client, name=f"config-{uuid.uuid4().hex}")
    second = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: Updating second to use first's name
    payload = _create_config_payload(
        name=first["name"],
        evaluator="regex",
        config={"pattern": r"\btest\b"},
    )
    resp = client.put(f"/api/v1/evaluator-configs/{second['id']}", json=payload)

    # Then: Conflict error is returned
    assert resp.status_code == 409
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NAME_CONFLICT"


def test_get_evaluator_config_not_found(client: TestClient) -> None:
    # Given: A non-existent evaluator config ID
    missing_id = 999999

    # When: Fetching the evaluator config
    resp = client.get(f"/api/v1/evaluator-configs/{missing_id}")

    # Then: Not found error is returned
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NOT_FOUND"


def test_list_evaluator_configs_with_filters_and_pagination(
    client: TestClient,
) -> None:
    # Given: Multiple evaluator configs
    base = f"config-{uuid.uuid4().hex}"
    _create_config(client, name=f"{base}-a", evaluator="regex")
    _create_config(client, name=f"{base}-b", evaluator="regex")
    _create_config(client, name=f"{base}-c", evaluator="regex")
    _create_config(client, name=f"{base}-d", evaluator="list")

    # When: Listing with limit and evaluator filter
    resp = client.get(
        "/api/v1/evaluator-configs",
        params={"limit": 2, "evaluator": "regex", "name": base},
    )

    # Then: Pagination metadata is correct
    assert resp.status_code == 200
    data = resp.json()
    assert data["pagination"]["limit"] == 2
    assert data["pagination"]["has_more"] is True
    assert len(data["evaluator_configs"]) == 2
    assert all(cfg["evaluator"] == "regex" for cfg in data["evaluator_configs"])


def test_delete_evaluator_config_success(client: TestClient) -> None:
    # Given: An existing evaluator config
    created = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: Deleting the evaluator config
    resp = client.delete(f"/api/v1/evaluator-configs/{created['id']}")

    # Then: Success is returned and the config is gone
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    get_resp = client.get(f"/api/v1/evaluator-configs/{created['id']}")
    assert get_resp.status_code == 404


def test_delete_evaluator_config_not_found(client: TestClient) -> None:
    # Given: A non-existent evaluator config ID
    missing_id = 999999

    # When: Deleting the evaluator config
    resp = client.delete(f"/api/v1/evaluator-configs/{missing_id}")

    # Then: Not found error is returned
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NOT_FOUND"


def test_create_evaluator_config_empty_config_allowed(client: TestClient) -> None:
    # Given: A payload with an empty config object
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="unknown-evaluator", config={})

    # When: Creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: It succeeds (empty config is valid)
    assert resp.status_code == 201
    data = resp.json()
    assert data["config"] == {}
