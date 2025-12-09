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
        "plugin": "list",
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
    
    # Verify error message mentions the field
    errors = resp.json()["detail"]
    assert any("logic" in str(e["loc"]) for e in errors)
    assert any("any" in e["msg"] or "all" in e["msg"] for e in errors)


def test_validation_discriminator_mismatch(client: TestClient):
    """Test that config must match the evaluator type."""
    control_id = create_control(client)
    
    # Given: type='list' but config has 'pattern' (RegexConfig)
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["evaluator"] = {
        "plugin": "list", 
        "config": {
            "pattern": "some_regex", # Invalid for ListConfig
            # Missing 'values'
        }
    }
    
    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    
    # Then: 422 Unprocessable Entity
    assert resp.status_code == 422
    
    # Verify error mentions missing required field for ListConfig
    errors = resp.json()["detail"]
    # Expecting 'values' field missing
    assert any("values" in str(e["loc"]) for e in errors)
    assert any("Field required" in e["msg"] for e in errors)


def test_validation_regex_flags_list(client: TestClient):
    """Test validation of regex flags list."""
    control_id = create_control(client)
    
    # Given: regex config with invalid flags type (string instead of list)
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["evaluator"] = {
        "plugin": "regex",
        "config": {
            "pattern": "abc",
            "flags": "IGNORECASE" # Should be ["IGNORECASE"]
        }
    }
    
    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    
    # Then: 422
    assert resp.status_code == 422
    errors = resp.json()["detail"]
    assert any("flags" in str(e["loc"]) for e in errors)


def test_validation_invalid_regex_pattern(client: TestClient):
    """Test validation of regex pattern syntax."""
    control_id = create_control(client)
    
    # Given: regex config with invalid pattern (unclosed bracket)
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["evaluator"] = {
        "plugin": "regex",
        "config": {
            "pattern": "[", # Invalid regex
            "flags": []
        }
    }
    
    # When: Setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    
    # Then: 422 Unprocessable Entity
    assert resp.status_code == 422
    
    errors = resp.json()["detail"]
    # Verify error message mentions regex compilation failure
    assert any("pattern" in str(e["loc"]) for e in errors)
    assert any("Invalid regex pattern" in e["msg"] for e in errors)
