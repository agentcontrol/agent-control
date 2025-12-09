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


def test_get_control_data_initially_empty(client: TestClient) -> None:
    # Given: a newly created control
    control_id = create_control(client)
    # When: fetching its data
    resp = client.get(f"/api/v1/controls/{control_id}/data")
    # Then: data is an empty object
    assert resp.status_code == 200
    assert resp.json()["data"] == {}


VALID_CONTROL_DATA = {
    "description": "Test Control",
    "enabled": True,
    "applies_to": "llm_call",
    "check_stage": "pre",
    "selector": {"path": "input"},
    "evaluator": {
        "plugin": "regex",
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
    # Then: data matches payload exactly
    assert resp_get.status_code == 200
    assert resp_get.json()["data"] == payload


def test_set_control_data_with_empty_dict_fails(client: TestClient) -> None:
    # Given: a control with non-empty data
    control_id = create_control(client)
    # When: setting empty dict
    # Then: Fails 422 because strict schema is enforced
    resp_put = client.put(f"/api/v1/controls/{control_id}/data", json={"data": {}})
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
