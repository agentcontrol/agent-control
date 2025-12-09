"""Tests for custom evaluator management endpoints.

Tests the full flow of:
1. Register custom evaluator via PUT /evaluators
2. Use it in a Control for /evaluation
3. List/get evaluators via GET /evaluators
4. Delete evaluator (blocked if in use)
"""

import uuid

import pytest
from agent_control_models import EvaluationRequest, LlmCall
from fastapi.testclient import TestClient

from .utils import create_and_assign_policy


# =============================================================================
# Test Data
# =============================================================================

# Simple string matcher evaluator code
STRING_MATCHER_CODE = '''
def evaluate(data, config):
    """Check if data contains target string."""
    target = config["target"]
    case_sensitive = config.get("case_sensitive", True)

    data_str = str(data) if data is not None else ""
    check_target = target

    if not case_sensitive:
        data_str = data_str.lower()
        check_target = target.lower()

    matched = check_target in data_str
    return EvaluatorResult(
        matched=matched,
        confidence=1.0,
        message=f"Match for '{target}': {matched}"
    )
'''

STRING_MATCHER_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string"},
        "case_sensitive": {"type": "boolean", "default": True},
    },
    "required": ["target"],
}


# =============================================================================
# Test: Evaluator Registration
# =============================================================================


class TestEvaluatorRegistration:
    """Tests for PUT /api/v1/evaluators endpoint."""

    def test_register_custom_evaluator(self, client: TestClient):
        """Test registering a new custom evaluator."""
        # Given: Valid evaluator definition
        name = f"test-matcher-{uuid.uuid4().hex[:8]}"

        # When: Registering the evaluator
        resp = client.put(
            "/api/v1/evaluators",
            json={
                "name": name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,
                "description": "Test string matcher",
            },
        )

        # Then: Evaluator is created
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == name
        assert "evaluator_id" in data

    def test_update_existing_evaluator(self, client: TestClient):
        """Test updating an existing custom evaluator."""
        # Given: Existing evaluator
        name = f"test-updatable-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={"name": name, "code": STRING_MATCHER_CODE, "description": "V1"},
        )

        # When: Updating with new description
        resp = client.put(
            "/api/v1/evaluators",
            json={"name": name, "code": STRING_MATCHER_CODE, "description": "V2"},
        )

        # Then: Update succeeds
        assert resp.status_code == 200

        # And: Description is updated
        detail = client.get(f"/api/v1/evaluators/{name}")
        assert detail.json()["description"] == "V2"

    def test_reject_reserved_name(self, client: TestClient):
        """Test rejecting evaluator names that conflict with built-in plugins."""
        # Given: Reserved plugin name 'regex'

        # When: Attempting to register with reserved name
        resp = client.put(
            "/api/v1/evaluators",
            json={"name": "regex", "code": STRING_MATCHER_CODE},
        )

        # Then: Rejected with 409 Conflict
        assert resp.status_code == 409
        assert "conflicts with built-in" in resp.json()["detail"]

    def test_reject_invalid_syntax(self, client: TestClient):
        """Test rejecting code with syntax errors."""
        # Given: Invalid Python code
        bad_code = "def evaluate(data, config):\n    return invalid syntax here"

        # When: Attempting to register
        resp = client.put(
            "/api/v1/evaluators",
            json={"name": f"bad-{uuid.uuid4().hex[:8]}", "code": bad_code},
        )

        # Then: Rejected with 422
        assert resp.status_code == 422
        assert "syntax error" in resp.json()["detail"].lower()


# =============================================================================
# Test: Evaluator Discovery
# =============================================================================


class TestEvaluatorDiscovery:
    """Tests for GET /api/v1/evaluators and GET /api/v1/plugins."""

    def test_list_evaluators(self, client: TestClient):
        """Test listing custom evaluators."""
        # Given: Registered evaluator
        name = f"test-listable-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={
                "name": name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,
            },
        )

        # When: Listing evaluators
        resp = client.get("/api/v1/evaluators")

        # Then: Our evaluator appears
        assert resp.status_code == 200
        evaluators = resp.json()
        names = [e["name"] for e in evaluators]
        assert name in names

    def test_get_evaluator_details(self, client: TestClient):
        """Test getting full evaluator details including code."""
        # Given: Registered evaluator
        name = f"test-detail-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={
                "name": name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,
                "description": "Details test",
            },
        )

        # When: Getting evaluator by name
        resp = client.get(f"/api/v1/evaluators/{name}")

        # Then: Full details returned
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == name
        assert data["code"] == STRING_MATCHER_CODE
        assert data["config_schema"] == STRING_MATCHER_SCHEMA
        assert data["description"] == "Details test"

    def test_evaluator_in_plugins_list(self, client: TestClient):
        """Test that custom evaluators appear in /plugins endpoint."""
        # Given: Registered evaluator
        name = f"test-plugin-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={
                "name": name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,
            },
        )

        # When: Listing plugins
        resp = client.get("/api/v1/plugins")

        # Then: Custom evaluator appears with is_custom=True
        assert resp.status_code == 200
        plugins = resp.json()
        assert name in plugins
        assert plugins[name]["is_custom"] is True
        assert plugins[name]["config_schema"] == STRING_MATCHER_SCHEMA


# =============================================================================
# Test: Evaluator Usage in /evaluation
# =============================================================================


class TestEvaluatorUsage:
    """Tests for using custom evaluators via /evaluation endpoint."""

    def test_evaluation_with_custom_evaluator_match(self, client: TestClient):
        """Test custom evaluator matches correctly via /evaluation."""
        # Given: Registered custom evaluator
        eval_name = f"test-eval-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={
                "name": eval_name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,
            },
        )

        # And: Control using the custom evaluator
        control_data = {
            "description": f"Block using {eval_name}",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {"user_config": {"target": "blocked"}},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, control_name = create_and_assign_policy(
            client, control_data, agent_name=f"EvalAgent-{uuid.uuid4().hex[:8]}"
        )

        # When: Evaluating input containing 'blocked'
        payload = LlmCall(input="This contains blocked content", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Request is denied
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_safe"] is False
        assert len(data["matches"]) == 1
        assert data["matches"][0]["control_name"] == control_name

    def test_evaluation_with_custom_evaluator_no_match(self, client: TestClient):
        """Test custom evaluator allows clean content."""
        # Given: Registered custom evaluator
        eval_name = f"test-eval-nomatch-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={
                "name": eval_name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,
            },
        )

        # And: Control using the custom evaluator
        control_data = {
            "description": f"Block using {eval_name}",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {"user_config": {"target": "secret"}},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, _ = create_and_assign_policy(
            client, control_data, agent_name=f"EvalAgentClean-{uuid.uuid4().hex[:8]}"
        )

        # When: Evaluating input that does NOT contain 'secret'
        payload = LlmCall(input="This is totally safe content", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Request is allowed
        assert resp.status_code == 200
        assert resp.json()["is_safe"] is True


# =============================================================================
# Test: Evaluator Deletion
# =============================================================================


class TestEvaluatorDeletion:
    """Tests for DELETE /api/v1/evaluators/{name}."""

    def test_delete_unused_evaluator(self, client: TestClient):
        """Test deleting an evaluator not in use."""
        # Given: Registered evaluator (not used by any Control)
        name = f"test-deletable-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={"name": name, "code": STRING_MATCHER_CODE},
        )

        # When: Deleting the evaluator
        resp = client.delete(f"/api/v1/evaluators/{name}")

        # Then: Delete succeeds
        assert resp.status_code == 204

        # And: Evaluator is gone
        resp = client.get(f"/api/v1/evaluators/{name}")
        assert resp.status_code == 404

    def test_delete_nonexistent_evaluator(self, client: TestClient):
        """Test deleting a non-existent evaluator returns 404."""
        # When: Deleting non-existent evaluator
        resp = client.delete("/api/v1/evaluators/does-not-exist")

        # Then: Returns 404
        assert resp.status_code == 404


# =============================================================================
# Test: Config Validation at Control Save Time
# =============================================================================


class TestEvaluatorConfigValidation:
    """Tests for config validation when saving Controls with custom evaluators."""

    def test_reject_invalid_config_missing_required(self, client: TestClient):
        """Test that saving a Control with invalid config returns 422."""
        # Given: Custom evaluator with schema requiring 'target' field
        eval_name = f"test-schema-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={
                "name": eval_name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,  # requires 'target'
            },
        )

        # When: Creating control with config missing required 'target'
        control_name = f"control-{uuid.uuid4().hex[:8]}"
        resp = client.put("/api/v1/controls", json={"name": control_name})
        control_id = resp.json()["control_id"]

        control_data = {
            "description": "Test control",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {
                    "user_config": {
                        "case_sensitive": True,  # Missing required 'target'!
                    }
                },
            },
            "action": {"decision": "deny"},
        }
        resp = client.put(
            f"/api/v1/controls/{control_id}/data", json={"data": control_data}
        )

        # Then: Returns 422 with validation error
        assert resp.status_code == 422
        assert "target" in resp.json()["detail"].lower()

    def test_reject_unknown_plugin(self, client: TestClient):
        """Test that saving a Control with unknown plugin returns 422."""
        # Given: No evaluator registered with name 'nonexistent-plugin'

        # When: Creating control referencing unknown plugin
        control_name = f"control-{uuid.uuid4().hex[:8]}"
        resp = client.put("/api/v1/controls", json={"name": control_name})
        control_id = resp.json()["control_id"]

        control_data = {
            "description": "Test control",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "nonexistent-plugin",
                "config": {},
            },
            "action": {"decision": "deny"},
        }
        resp = client.put(
            f"/api/v1/controls/{control_id}/data", json={"data": control_data}
        )

        # Then: Returns 422 with helpful message
        assert resp.status_code == 422
        assert "unknown plugin" in resp.json()["detail"].lower()

    def test_accept_valid_config(self, client: TestClient):
        """Test that saving a Control with valid config succeeds."""
        # Given: Custom evaluator with schema
        eval_name = f"test-valid-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={
                "name": eval_name,
                "code": STRING_MATCHER_CODE,
                "config_schema": STRING_MATCHER_SCHEMA,
            },
        )

        # When: Creating control with valid config
        control_name = f"control-{uuid.uuid4().hex[:8]}"
        resp = client.put("/api/v1/controls", json={"name": control_name})
        control_id = resp.json()["control_id"]

        control_data = {
            "description": "Test control",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {
                    "user_config": {
                        "target": "blocked",  # Required field present
                        "case_sensitive": False,
                    }
                },
            },
            "action": {"decision": "deny"},
        }
        resp = client.put(
            f"/api/v1/controls/{control_id}/data", json={"data": control_data}
        )

        # Then: Succeeds
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# =============================================================================
# Test: Custom Code Features
# =============================================================================


class TestCustomCodeFeatures:
    """Tests for custom evaluator code execution features."""

    def test_import_re2_in_custom_code(self, client: TestClient):
        """Test that custom code can import re2 for regex matching."""
        # Given: Custom evaluator that imports re2
        re2_code = '''
def evaluate(data, config):
    import re2
    pattern = config["pattern"]
    text = str(data) if data else ""
    if re2.search(pattern, text):
        return EvaluatorResult(matched=True, confidence=1.0, message="Pattern matched")
    return EvaluatorResult(matched=False, confidence=1.0, message="No match")
'''
        eval_name = f"re2-matcher-{uuid.uuid4().hex[:8]}"
        resp = client.put(
            "/api/v1/evaluators",
            json={
                "name": eval_name,
                "code": re2_code,
                "config_schema": {
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
            },
        )
        assert resp.status_code == 200

        # And: Control using the evaluator to match SSN pattern
        control_data = {
            "description": "Match SSN with re2",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {"user_config": {"pattern": r"\d{3}-\d{2}-\d{4}"}},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, control_name = create_and_assign_policy(
            client, control_data, agent_name=f"Re2Agent-{uuid.uuid4().hex[:8]}"
        )

        # When: Evaluating input containing SSN
        payload = LlmCall(input="My SSN is 123-45-6789", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Pattern is matched
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_safe"] is False
        assert data["matches"][0]["control_name"] == control_name

    def test_runtime_error_returns_error_in_result(self, client: TestClient):
        """Test that runtime errors are captured and returned in the result."""
        # Given: Custom evaluator that throws an exception
        error_code = '''
def evaluate(data, config):
    raise ValueError("Intentional test error")
'''
        eval_name = f"error-thrower-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={"name": eval_name, "code": error_code},
        )

        # And: Control using the error-throwing evaluator
        control_data = {
            "description": "Error test",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {"user_config": {}, "on_error": "deny"},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, control_name = create_and_assign_policy(
            client, control_data, agent_name=f"ErrorAgent-{uuid.uuid4().hex[:8]}"
        )

        # When: Evaluating (triggers runtime error)
        payload = LlmCall(input="test", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Request returns 200 but with error info in match
        assert resp.status_code == 200
        data = resp.json()
        # With on_error=deny, matched=True so is_safe=False
        assert data["is_safe"] is False
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        assert match["control_name"] == control_name
        # Error details in result metadata
        result = match["result"]
        assert "error" in result["message"].lower()
        assert result["metadata"]["error"] == "Intentional test error"
        assert result["metadata"]["error_type"] == "ValueError"

    def test_runtime_error_with_on_error_allow(self, client: TestClient):
        """Test that on_error=allow causes errors to not match."""
        # Given: Custom evaluator that throws an exception
        error_code = '''
def evaluate(data, config):
    raise RuntimeError("Something went wrong")
'''
        eval_name = f"error-allow-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={"name": eval_name, "code": error_code},
        )

        # And: Control with on_error=allow (fail open)
        control_data = {
            "description": "Error allow test",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {"user_config": {}, "on_error": "allow"},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, _ = create_and_assign_policy(
            client, control_data, agent_name=f"ErrorAllowAgent-{uuid.uuid4().hex[:8]}"
        )

        # When: Evaluating (triggers runtime error)
        payload = LlmCall(input="test", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: With on_error=allow, matched=False so request is safe
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_safe"] is True
        # No matches because error resulted in matched=False
        assert data["matches"] is None or len(data["matches"]) == 0

    def test_module_level_state_persists_across_calls(self, client: TestClient):
        """Test that module-level state in custom code persists across evaluate() calls."""
        # Given: Custom evaluator with a counter that increments on each call
        counter_code = '''
# Module-level state - persists across calls
_call_count = 0

def evaluate(data, config):
    global _call_count
    _call_count += 1
    return EvaluatorResult(
        matched=True,  # Always match so we get result in response
        confidence=1.0,
        message=f"Call count: {_call_count}",
        metadata={"call_count": _call_count}
    )
'''
        eval_name = f"counter-{uuid.uuid4().hex[:8]}"
        client.put(
            "/api/v1/evaluators",
            json={"name": eval_name, "code": counter_code},
        )

        # And: Control using the counter evaluator with 'log' action (safe)
        control_data = {
            "description": "Counter test",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": eval_name,
                "config": {"user_config": {}},
            },
            "action": {"decision": "log"},  # 'log' means is_safe=True even when matched
        }
        agent_uuid, _ = create_and_assign_policy(
            client, control_data, agent_name=f"CounterAgent-{uuid.uuid4().hex[:8]}"
        )

        # When: Calling evaluate multiple times
        counts = []
        for i in range(3):
            payload = LlmCall(input=f"test {i}", output=None)
            req = EvaluationRequest(
                agent_uuid=agent_uuid, payload=payload, check_stage="pre"
            )
            resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))
            assert resp.status_code == 200
            data = resp.json()
            # matched=True so we should have matches
            assert data.get("matches"), f"Expected matches on call {i}"
            count = data["matches"][0]["result"]["metadata"]["call_count"]
            counts.append(count)

        # Then: Call count should increment (state persists)
        # If state didn't persist, count would be 1 each time
        assert counts == [1, 2, 3], f"Expected [1, 2, 3], got {counts}"
