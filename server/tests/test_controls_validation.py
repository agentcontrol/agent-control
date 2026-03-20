"""Tests for control validation and schema enforcement."""

import uuid
from copy import deepcopy

from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD


def create_control(client: TestClient) -> int:
    name = f"control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": name, "data": VALID_CONTROL_PAYLOAD})
    assert resp.status_code == 200
    return resp.json()["control_id"]

def test_validation_invalid_logic_enum(client: TestClient):
    """Test that invalid enum values in config are rejected."""
    # Given: a control and a payload with invalid 'logic' value
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {
        "name": "list",
        "config": {
            "values": ["a", "b"],
            "logic": "invalid_logic", # Should be 'any' or 'all'
            "match_on": "match"
        }
    }

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity
    assert resp.status_code == 422

    # Then: error message mentions the field (RFC 7807 format)
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("logic" in str(e.get("field", "")) for e in errors)
    assert any("any" in e.get("message", "") or "all" in e.get("message", "") for e in errors)


def test_validation_discriminator_mismatch(client: TestClient):
    """Test that config must match the evaluator type."""
    # Given: a control and type='list' but config has 'pattern' (RegexEvaluatorConfig)
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {
        "name": "list",
        "config": {
            "pattern": "some_regex", # Invalid for ListEvaluatorConfig
            # Missing 'values'
        }
    }

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity
    assert resp.status_code == 422

    # Then: error mentions missing required field for ListEvaluatorConfig (RFC 7807 format)
    response_data = resp.json()
    errors = response_data.get("errors", [])
    # Expecting 'values' field missing
    assert any("values" in str(e.get("field", "")) for e in errors)
    assert any("Field required" in e.get("message", "") for e in errors)


def test_validation_regex_flags_list(client: TestClient):
    """Test validation of regex flags list."""
    # Given: a control and regex config with invalid flags type (string instead of list)
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {
        "name": "regex",
        "config": {
            "pattern": "abc",
            "flags": "IGNORECASE" # Should be ["IGNORECASE"]
        }
    }

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 (RFC 7807 format)
    assert resp.status_code == 422
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("flags" in str(e.get("field", "")) for e in errors)


def test_validation_list_values_reject_blank_strings(client: TestClient):
    """Test that list evaluator config rejects empty and whitespace-only entries."""
    # Given: a control and a list evaluator payload with a whitespace-only value
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {
        "name": "list",
        "config": {
            "values": [" "],
            "logic": "any",
            "match_on": "match",
            "match_mode": "contains",
        },
    }

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: the invalid config is rejected
    assert resp.status_code == 422
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("values" in str(e.get("field", "")) for e in errors)
    assert any("empty or whitespace-only strings" in e.get("message", "") for e in errors)


def test_validation_invalid_regex_pattern(client: TestClient):
    """Test validation of regex pattern syntax."""
    # Given: a control and regex config with invalid pattern (unclosed bracket)
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {
        "name": "regex",
        "config": {
            "pattern": "[", # Invalid regex
            "flags": []
        }
    }

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity (RFC 7807 format)
    assert resp.status_code == 422

    response_data = resp.json()
    errors = response_data.get("errors", [])
    # Then: error message mentions regex compilation failure
    assert any("pattern" in str(e.get("field", "")) for e in errors)
    assert any("Invalid regex pattern" in e.get("message", "") for e in errors)


def test_validation_empty_string_path_rejected(client: TestClient):
    """Test that empty string path is rejected."""
    # Given: a control and payload with empty string path
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["selector"] = {"path": ""}

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity (RFC 7807 format)
    assert resp.status_code == 422

    # Then: error message mentions path
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("path" in str(e.get("field", "")).lower() for e in errors)
    assert any("empty string" in e.get("message", "") for e in errors)


def test_validation_none_path_defaults_to_star(client: TestClient):
    """Test that None/missing path defaults to '*'."""
    # Given: a control and payload without path in selector (None)
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["selector"] = {}  # No path specified

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: succeeds
    assert resp.status_code == 200, resp.text

    # When: reading back
    get_resp = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: reading back the control succeeds
    assert get_resp.status_code == 200

    # Then: path should default to '*'
    data = get_resp.json()["data"]
    assert data["condition"]["selector"]["path"] == "*"


def test_get_control_data_returns_typed_response(client: TestClient):
    """Test that GET control data returns a typed ControlDefinition."""
    # Given: a control shell
    control_id = create_control(client)

    # When: setting valid control data
    resp_put = client.put(
        f"/api/v1/controls/{control_id}/data", json={"data": VALID_CONTROL_PAYLOAD}
    )

    # Then: the control data is stored successfully
    assert resp_put.status_code == 200

    # When: getting control data
    resp_get = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: response should be typed with all expected fields
    assert resp_get.status_code == 200
    data = resp_get.json()["data"]

    # Then: the response includes required ControlDefinition fields
    assert "condition" in data
    assert "action" in data
    assert "execution" in data
    assert "scope" in data


def test_validation_empty_step_names_rejected(client: TestClient):
    """Test that empty step_names list is rejected."""
    # Given: a control and payload with empty step_names list
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["scope"] = {"step_names": []}

    # When: setting control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: 422 Unprocessable Entity (RFC 7807 format)
    assert resp.status_code == 422

    # Then: error message mentions step_names
    response_data = resp.json()
    errors = response_data.get("errors", [])
    assert any("step_names" in str(e.get("field", "")) for e in errors)
    assert any("empty list" in e.get("message", "") for e in errors)


def test_validation_nested_condition_error_uses_bracketed_field_path(
    client: TestClient,
):
    """Nested condition leaf errors should report full dot/bracket paths."""
    # Given: a nested condition whose first leaf has invalid evaluator config
    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"] = {
        "and": [
            {
                "selector": {"path": "input"},
                "evaluator": {
                    "name": "list",
                    "config": {
                        "values": ["a", "b"],
                        "logic": "invalid_logic",
                        "match_on": "match",
                    },
                },
            },
            {
                "selector": {"path": "output"},
                "evaluator": {
                    "name": "regex",
                    "config": {"pattern": "ok"},
                },
            },
        ]
    }

    # When: validating the nested control definition through the API
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: the error points at the exact nested leaf path
    assert resp.status_code == 422
    errors = resp.json().get("errors", [])
    assert any(
        err.get("field") == "data.condition.and[0].evaluator.logic"
        for err in errors
    )


def test_validation_nested_agent_scoped_evaluator_error_uses_bracketed_field_path(
    client: TestClient,
):
    """Nested agent-scoped evaluator failures should identify the exact leaf path."""
    # Given: an agent and a nested condition that references a missing agent evaluator
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name},
            "steps": [],
            "evaluators": [],
        },
    )
    assert init_resp.status_code == 200

    control_id = create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"] = {
        "or": [
            {
                "selector": {"path": "input"},
                "evaluator": {
                    "name": f"{agent_name}:missing-evaluator",
                    "config": {},
                },
            }
        ]
    }

    # When: validating the nested control definition through the API
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: the error points at the exact nested evaluator name field
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "EVALUATOR_NOT_FOUND"
    assert any(
        err.get("field") == "data.condition.or[0].evaluator.name"
        and err.get("code") == "evaluator_not_found"
        for err in body.get("errors", [])
    )
