"""Tests for control validation and schema enforcement."""
import uuid
from fastapi.testclient import TestClient
from .utils import VALID_CONTROL_PAYLOAD

def create_control(client: TestClient) -> int:
    name = f"control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": name})
    assert resp.status_code == 200
    return resp.json()["control_id"]

def test_validation_invalid_logic_enum(client: TestClient):
    """Test that invalid enum values in config are rejected."""
    control_id = create_control(client)
    
    # Given: Payload with invalid 'logic' value
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["evaluator"] = {
        "name": "list",
        "config": {
            "values": ["a", "b"],
            "logic": "invalid_logic", # Should be 'any' or 'all'
            "match_on": "match"
        }
    }
    
    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    
    # Then: 422 Unprocessable Entity
    assert resp.status_code == 422
    
    # Verify error message mentions the field (RFC 7807 format)
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("logic" in str(e.get("field", "")) for e in errors)
    assert any("any" in e.get("message", "") or "all" in e.get("message", "") for e in errors)


def test_validation_discriminator_mismatch(client: TestClient):
    """Test that config must match the evaluator type."""
    control_id = create_control(client)
    
    # Given: type='list' but config has 'pattern' (RegexEvaluatorConfig)
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["evaluator"] = {
        "name": "list",
        "config": {
            "pattern": "some_regex", # Invalid for ListEvaluatorConfig
            # Missing 'values'
        }
    }

    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity
    assert resp.status_code == 422

    # Verify error mentions missing required field for ListEvaluatorConfig (RFC 7807 format)
    response_data = resp.json()
    errors = response_data.get("errors", [])
    # Expecting 'values' field missing
    assert any("values" in str(e.get("field", "")) for e in errors)
    assert any("Field required" in e.get("message", "") for e in errors)


def test_validation_regex_flags_list(client: TestClient):
    """Test validation of regex flags list."""
    control_id = create_control(client)
    
    # Given: regex config with invalid flags type (string instead of list)
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["evaluator"] = {
        "name": "regex",
        "config": {
            "pattern": "abc",
            "flags": "IGNORECASE" # Should be ["IGNORECASE"]
        }
    }
    
    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    
    # Then: 422 (RFC 7807 format)
    assert resp.status_code == 422
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("flags" in str(e.get("field", "")) for e in errors)


def test_validation_invalid_regex_pattern(client: TestClient):
    """Test validation of regex pattern syntax."""
    control_id = create_control(client)
    
    # Given: regex config with invalid pattern (unclosed bracket)
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["evaluator"] = {
        "name": "regex",
        "config": {
            "pattern": "[", # Invalid regex
            "flags": []
        }
    }
    
    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    
    # Then: 422 Unprocessable Entity (RFC 7807 format)
    assert resp.status_code == 422
    
    response_data = resp.json()
    errors = response_data.get("errors", [])
    # Verify error message mentions regex compilation failure
    assert any("pattern" in str(e.get("field", "")) for e in errors)
    assert any("Invalid regex pattern" in e.get("message", "") for e in errors)


def test_validation_empty_string_path_rejected(client: TestClient):
    """Test that empty string path is rejected."""
    control_id = create_control(client)

    # Given: Payload with empty string path
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["selector"] = {"path": ""}

    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity (RFC 7807 format)
    assert resp.status_code == 422

    # Verify error message mentions path
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("path" in str(e.get("field", "")).lower() for e in errors)
    assert any("empty string" in e.get("message", "") for e in errors)


def test_validation_none_path_defaults_to_star(client: TestClient):
    """Test that None/missing path defaults to '*'."""
    control_id = create_control(client)

    # Given: Payload without path in selector (None)
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["selector"] = {}  # No path specified

    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: Succeeds
    assert resp.status_code == 200, resp.text

    # When: Reading back
    get_resp = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_resp.status_code == 200

    # Then: path should default to '*'
    data = get_resp.json()["data"]
    assert data["selector"]["path"] == "*"


def test_get_control_data_returns_typed_response(client: TestClient):
    """Test that GET control data returns a typed ControlDefinition."""
    control_id = create_control(client)

    # Given: Set valid control data
    resp_put = client.put(
        f"/api/v1/controls/{control_id}/data", json={"data": VALID_CONTROL_PAYLOAD}
    )
    assert resp_put.status_code == 200

    # When: Getting control data
    resp_get = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: Response should be typed with all expected fields
    assert resp_get.status_code == 200
    data = resp_get.json()["data"]

    # Should have required ControlDefinition fields
    assert "evaluator" in data
    assert "action" in data
    assert "selector" in data
    assert "execution" in data
    assert "scope" in data


def test_validation_empty_step_names_rejected(client: TestClient):
    """Test that empty step_names list is rejected."""
    control_id = create_control(client)

    # Given: Payload with empty step_names list
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["scope"] = {"step_names": []}

    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity (RFC 7807 format)
    assert resp.status_code == 422

    # Verify error message mentions step_names
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("step_names" in str(e.get("field", "")) for e in errors)
    assert any("empty list" in e.get("message", "") for e in errors)
