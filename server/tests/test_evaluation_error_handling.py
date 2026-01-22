"""End-to-end tests for evaluator error handling."""
import uuid

from agent_control_models import EvaluationRequest, LlmCall
from fastapi.testclient import TestClient

from .utils import create_and_assign_policy


def test_evaluation_with_agent_scoped_evaluator_missing(client: TestClient):
    """Test that referencing missing agent evaluator fails at policy assignment.

    Given: A control referencing agent:evaluator that doesn't exist
    When: Attempting to assign policy
    Then: Returns 400 with clear error message
    """
    # Given: Agent without evaluators
    agent_uuid = uuid.uuid4()
    client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_id": str(agent_uuid),
            "agent_name": f"TestAgent-{uuid.uuid4().hex[:8]}"
        },
        "tools": [],
        "evaluators": []
    })

    # And: A control referencing non-existent agent evaluator
    agent_name = f"TestAgent-{uuid.uuid4().hex[:8]}"
    control_data = {
        "description": "Test control",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "pre",
        "selector": {"path": "input"},
        "evaluator": {
            "plugin": f"{agent_name}:missing-evaluator",
            "config": {}
        },
        "action": {"decision": "deny"}
    }

    # When: Creating control - this should fail at control creation
    control_resp = client.put("/api/v1/controls", json={"name": f"control-{uuid.uuid4().hex[:8]}"})
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    # Then: Setting control data should fail if agent doesn't exist
    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": control_data})
    # This will fail because the agent doesn't exist yet
    assert set_resp.status_code in [404, 422]


def test_evaluation_control_with_invalid_config_caught_early(client: TestClient):
    """Test that invalid evaluator config is caught at control creation.

    Given: A control with invalid config for a plugin
    When: Setting control data
    Then: Returns 422 with validation error
    """
    # Given: Create control
    control_resp = client.put("/api/v1/controls", json={"name": f"control-{uuid.uuid4().hex[:8]}"})
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    # When: Setting control data with invalid regex config (missing required 'pattern')
    control_data = {
        "description": "Test control",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "pre",
        "selector": {"path": "input"},
        "evaluator": {
            "plugin": "regex",
            "config": {}  # Missing required 'pattern' field
        },
        "action": {"decision": "deny"}
    }

    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": control_data})

    # Then: Should fail with validation error
    assert set_resp.status_code == 422
    assert "pattern" in set_resp.text.lower() or "required" in set_resp.text.lower()


def test_evaluation_errors_field_populated_on_evaluator_failure(
    client: TestClient, monkeypatch
):
    """Test that errors field is populated when evaluator fails at runtime.

    Given: A valid control with a plugin that crashes during evaluation
    When: Evaluation is requested
    Then: Response has errors field populated and is_safe=False (for deny)
    """
    from unittest.mock import AsyncMock, MagicMock

    # Given: Setup agent with a working control
    control_data = {
        "description": "Test control",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "pre",
        "selector": {"path": "input"},
        "evaluator": {
            "plugin": "regex",
            "config": {"pattern": "test"}
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data)

    # Mock get_evaluator to return a plugin that throws
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(side_effect=RuntimeError("Simulated plugin crash"))
    mock_evaluator.get_timeout_seconds = MagicMock(return_value=30.0)

    # Patch where it's used (in core module), not where it's defined
    import agent_control_engine.core as core_module

    def mock_get_evaluator(config):
        return mock_evaluator

    monkeypatch.setattr(core_module, "get_evaluator", mock_get_evaluator)

    # When: Sending evaluation request
    payload = LlmCall(input="test content", output=None)
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=payload,
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: Response should have errors field populated
    assert resp.status_code == 200
    data = resp.json()

    # is_safe=False because deny control errored (fail closed)
    assert data["is_safe"] is False

    # Confidence should be 0 (no successful evaluations)
    assert data["confidence"] == 0.0

    # Errors field should be populated
    assert data["errors"] is not None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["control_name"] == control_name
    assert "RuntimeError" in data["errors"][0]["result"]["error"]
    assert "Simulated plugin crash" in data["errors"][0]["result"]["error"]

    # No matches because evaluation failed
    assert data["matches"] is None or len(data["matches"]) == 0
