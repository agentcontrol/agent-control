from typing import Any
import uuid

from fastapi.testclient import TestClient


def create_control(client: TestClient) -> int:
    name = f"control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": name})
    assert resp.status_code == 200
    cid = resp.json()["control_id"]
    assert isinstance(cid, int)
    return cid


def test_create_control_returns_id(client: TestClient) -> None:
    # Given: no prior controls
    # When: creating a control via API
    resp = client.put("/api/v1/controls", json={"name": f"control-{uuid.uuid4()}"})
    # Then: a control_id is returned (integer)
    assert resp.status_code == 200
    assert isinstance(resp.json()["control_id"], int)


def test_get_control_data_initially_unconfigured(client: TestClient) -> None:
    # Given: a newly created control (no data set yet)
    control_id = create_control(client)
    # When: fetching its data
    resp = client.get(f"/api/v1/controls/{control_id}/data")
    # Then: 422 because empty data is not a valid ControlDefinition (RFC 7807 format)
    assert resp.status_code == 422
    response_data = resp.json()
    assert "invalid data" in response_data.get("detail", "").lower()


VALID_CONTROL_DATA = {
    "description": "Test Control",
    "enabled": True,
    "execution": "server",
    "scope": {"step_types": ["llm"], "stages": ["pre"]},
    "selector": {"path": "input"},
    "evaluator": {
        "name": "regex",
        "config": {"pattern": "test", "flags": []}
    },
    "action": {"decision": "deny"},
    "tags": ["test"]
}

def test_set_control_data_replaces_existing(client: TestClient) -> None:
    # Given: a control with empty data
    control_id = create_control(client)
    # When: setting data
    payload = VALID_CONTROL_DATA
    resp_put = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    # Then: update succeeds
    assert resp_put.status_code == 200, resp_put.text
    assert resp_put.json()["success"] is True

    # When: reading back
    resp_get = client.get(f"/api/v1/controls/{control_id}/data")
    # Then: data matches payload (with defaults filled in)
    assert resp_get.status_code == 200
    data = resp_get.json()["data"]
    # Core fields should match
    assert data["description"] == payload["description"]
    assert data["enabled"] == payload["enabled"]
    assert data["execution"] == payload["execution"]
    assert data["scope"] == payload["scope"]
    assert data["evaluator"] == payload["evaluator"]
    assert data["action"] == payload["action"]
    assert data["selector"]["path"] == payload["selector"]["path"]


def test_set_control_data_with_empty_dict_fails(client: TestClient) -> None:
    # Given: a control with non-empty data
    control_id = create_control(client)
    # When: setting empty dict
    resp_put = client.put(f"/api/v1/controls/{control_id}/data", json={"data": {}})
    # Then: Fails 422 because strict schema is enforced
    assert resp_put.status_code == 422


def test_set_control_data_validates_nested_schema(client: TestClient) -> None:
    # Given: a control
    control_id = create_control(client)
    
    # When: setting invalid data (missing required fields)
    invalid_data = {"conditions": "test"} 
    r = client.put(f"/api/v1/controls/{control_id}/data", json={"data": invalid_data})
    
    # Then: 422 Validation Error
    assert r.status_code == 422

    # Given: a non-existent control id
    missing = "99999999"
    # When: fetching data
    r = client.get(f"/api/v1/controls/{missing}/data")
    # Then: 404
    assert r.status_code == 404


def test_set_control_data_round_trip_preserves_scope_step_names(client: TestClient) -> None:
    # Given: a control and a payload with step_names set (and other optional scope fields null)
    control_id = create_control(client)
    payload: dict[str, Any] = dict(VALID_CONTROL_DATA)
    payload["scope"] = {
        "step_names": ["step-a", "step-b"],
        "step_types": None,
        "stages": None,
        "step_name_regex": None,
    }

    # When: saving then reloading the control data
    put_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    assert put_resp.status_code == 200, put_resp.text

    get_resp = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_resp.status_code == 200, get_resp.text

    # Then: step_names are preserved across the round-trip
    data = get_resp.json()["data"]
    assert data["scope"]["step_names"] == ["step-a", "step-b"]


def test_set_control_data_not_found(client: TestClient) -> None:
    # Given: a non-existent control id
    missing = "99999999"
    # When: setting data
    r = client.put(f"/api/v1/controls/{missing}/data", json={"data": VALID_CONTROL_DATA})
    # Then: 404
    assert r.status_code == 404


def test_set_control_data_requires_body_with_data_key(client: TestClient) -> None:
    # Given: a control id
    control_id = create_control(client)

    # When: body is missing
    r1 = client.put(f"/api/v1/controls/{control_id}/data", json=None)
    # Then: 422 validation error
    assert r1.status_code == 422

    # When: body without 'data'
    r2 = client.put(f"/api/v1/controls/{control_id}/data", json={})
    # Then: 422 validation error
    assert r2.status_code == 422


def test_create_control_duplicate_name_409(client: TestClient) -> None:
    # Given: a specific control name
    name = f"dup-control-{uuid.uuid4()}"
    r1 = client.put("/api/v1/controls", json={"name": name})
    assert r1.status_code == 200
    # When: creating again with the same name
    r2 = client.put("/api/v1/controls", json={"name": name})
    # Then: conflict
    assert r2.status_code == 409


# =============================================================================
# GET /controls/{id} Tests
# =============================================================================


def test_get_control_returns_metadata(client: TestClient) -> None:
    """Test GET /controls/{id} returns control id, name, and data."""
    # Given: a control with a specific name
    name = f"test-control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": name})
    assert resp.status_code == 200
    control_id = resp.json()["control_id"]

    # When: fetching the control
    get_resp = client.get(f"/api/v1/controls/{control_id}")

    # Then: returns id, name, and data (None for unconfigured)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == control_id
    assert body["name"] == name
    assert body["data"] is None  # Not configured yet


def test_get_control_with_data(client: TestClient) -> None:
    """Test GET /controls/{id} returns data when configured."""
    # Given: a control with data set
    control_id = create_control(client)
    client.put(f"/api/v1/controls/{control_id}/data", json={"data": VALID_CONTROL_DATA})

    # When: fetching the control
    get_resp = client.get(f"/api/v1/controls/{control_id}")

    # Then: returns the configured data
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == control_id
    assert body["data"] is not None
    assert body["data"]["description"] == VALID_CONTROL_DATA["description"]
    assert body["data"]["execution"] == VALID_CONTROL_DATA["execution"]


def test_get_control_not_found(client: TestClient) -> None:
    """Test GET /controls/{id} returns 404 for non-existent control."""
    # Given: a non-existent control id
    missing_id = 99999999

    # When: fetching the control
    resp = client.get(f"/api/v1/controls/{missing_id}")

    # Then: 404 (RFC 7807 format)
    assert resp.status_code == 404
    response_data = resp.json()
    assert "not found" in response_data.get("detail", "").lower()
