"""End-to-end tests for evaluator error handling."""
import logging
import uuid

from fastapi.testclient import TestClient

from agent_control_models import EvaluationRequest, Step
from agent_control_server.observability.ingest.base import IngestResult
from .utils import create_and_assign_policy


def test_evaluation_with_agent_scoped_evaluator_missing(client: TestClient):
    """Test that referencing missing agent evaluator fails at policy assignment.

    Given: A control referencing agent:evaluator that doesn't exist
    When: Attempting to assign policy
    Then: Returns 400 with clear error message
    """
    # Given: an agent without evaluators
    agent_name = f"testagent-{uuid.uuid4().hex[:12]}"
    client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_name": agent_name
        },
        "steps": [],
        "evaluators": []
    })

    # And: a control referencing a non-existent agent evaluator
    control_data = {
        "description": "Test control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": f"{agent_name}:missing-evaluator",
            "config": {}
        },
        "action": {"decision": "deny"}
    }

    # When: creating the control shell
    control_resp = client.put("/api/v1/controls", json={"name": f"control-{uuid.uuid4().hex[:8]}"})
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    # When: setting control data with a missing agent-scoped evaluator
    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": control_data})

    # Then: a validation or not-found error is returned
    # This will fail because the agent doesn't exist yet
    assert set_resp.status_code in [404, 422]


def test_evaluation_control_with_invalid_config_caught_early(client: TestClient):
    """Test that invalid evaluator config is caught at control creation.

    Given: A control with invalid config for an evaluator
    When: Setting control data
    Then: Returns 422 with validation error
    """
    # Given: a control shell to configure
    control_resp = client.put("/api/v1/controls", json={"name": f"control-{uuid.uuid4().hex[:8]}"})
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    # When: setting control data with invalid regex config (missing required 'pattern')
    control_data = {
        "description": "Test control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": "regex",
            "config": {}  # Missing required 'pattern' field
        },
        "action": {"decision": "deny"}
    }

    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": control_data})

    # Then: a validation error is returned
    assert set_resp.status_code == 422
    assert "pattern" in set_resp.text.lower() or "required" in set_resp.text.lower()


def test_evaluation_errors_field_populated_on_evaluator_failure(
    client: TestClient, monkeypatch
):
    """Test that errors field is populated when evaluator fails at runtime.

    Given: A valid control with an evaluator that crashes during evaluation
    When: Evaluation is requested
    Then: Response has errors field populated and is_safe=False (for deny)
    """
    from unittest.mock import MagicMock, AsyncMock

    # Given: an agent with a working control
    control_data = {
        "description": "Test control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": "regex",
            "config": {"pattern": "test"}
        },
        "action": {"decision": "deny"}
    }
    agent_name, control_name = create_and_assign_policy(client, control_data)

    # And: an evaluator instance that throws during evaluation
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(side_effect=RuntimeError("Simulated evaluator crash"))
    mock_evaluator.get_timeout_seconds = MagicMock(return_value=30.0)

    # Patch where it's used (in core module), not where it's defined
    import agent_control_engine.core as core_module

    def mock_get_evaluator_instance(config):
        return mock_evaluator

    monkeypatch.setattr(core_module, "get_evaluator_instance", mock_get_evaluator_instance)

    # When: sending an evaluation request
    payload = Step(type="llm", name="test-step", input="test content", output=None)
    req = EvaluationRequest(
        agent_name=agent_name,
        step=payload,
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: the response reports an evaluation error
    assert resp.status_code == 200
    data = resp.json()

    # Then: is_safe is false because deny control errored (fail closed)
    assert data["is_safe"] is False

    # And: confidence is zero (no successful evaluations)
    assert data["confidence"] == 0.0

    # And: errors field is populated with the failing control
    assert data["errors"] is not None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["control_name"] == control_name
    assert (
        data["errors"][0]["result"]["error"]
        == "Evaluation failed due to an internal evaluator error."
    )
    assert "RuntimeError" not in data["errors"][0]["result"]["error"]
    assert "Simulated evaluator crash" not in data["errors"][0]["result"]["error"]

    # And: no matches are returned because evaluation failed
    assert data["matches"] is None or len(data["matches"]) == 0


def test_evaluation_engine_value_error_returns_422(client: TestClient, monkeypatch) -> None:
    """Test that evaluation returns 422 when the engine raises a ValueError."""
    # Given: a valid agent with a control assigned
    control_data = {
        "description": "Test control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
        "action": {"decision": "deny"},
    }
    agent_name, _ = create_and_assign_policy(client, control_data)

    # And: the engine raises a ValueError during processing
    import agent_control_engine.core as core_module

    async def raise_value_error(*_args, **_kwargs):
        raise ValueError("bad config")

    monkeypatch.setattr(core_module.ControlEngine, "process", raise_value_error)

    # When: sending an evaluation request
    payload = Step(type="llm", name="test-step", input="test content", output=None)
    req = EvaluationRequest(agent_name=agent_name, step=payload, stage="pre")
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: a validation error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "EVALUATION_FAILED"
    assert "bad config" not in body["detail"]
    assert body["errors"][0]["message"] == "Invalid evaluation request or control configuration."


def test_evaluation_warns_when_observability_drops_events(
    client: TestClient, app, caplog
) -> None:
    # Given: an agent with a control that will match
    agent_name, _ = create_and_assign_policy(client)

    class DroppingIngestor:
        async def ingest(self, events):  # type: ignore[no-untyped-def]
            return IngestResult(received=len(events), processed=0, dropped=len(events))

    previous_ingestor = getattr(app.state, "event_ingestor", None)
    app.state.event_ingestor = DroppingIngestor()
    try:
        # And: a log capture for the evaluation warning
        caplog.set_level(logging.WARNING, logger="agent_control_server.endpoints.evaluation")

        # When: sending an evaluation request
        payload = Step(type="llm", name="test-step", input="x", output=None)
        req = EvaluationRequest(agent_name=agent_name, step=payload, stage="pre")
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: the evaluation succeeds but logs a dropped-events warning
        assert resp.status_code == 200
        assert any("Dropped" in record.message for record in caplog.records)
    finally:
        if previous_ingestor is None:
            del app.state.event_ingestor
        else:
            app.state.event_ingestor = previous_ingestor
