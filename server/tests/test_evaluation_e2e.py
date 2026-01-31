"""End-to-end tests for evaluation flow."""
import uuid
from fastapi.testclient import TestClient
from agent_control_models import EvaluationRequest, Step
from .utils import create_and_assign_policy


def test_evaluation_flow_deny(client: TestClient):
    # Given: A registered agent with a policy blocking "secret"
    control_data = {
        "description": "Block secret",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": "regex",
            "config": {"pattern": "secret"}
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data)

    # When: Sending a request containing "secret"
    payload = Step(type="llm", name="test-step", input="This contains a secret", output=None)
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=payload,
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: It should be denied
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_safe"] is False
    assert len(data["matches"]) > 0
    assert data["matches"][0]["control_name"] == control_name


def test_evaluation_no_policy(client: TestClient):
    """Test that an agent with no policy assigned is safe."""
    # Given: an agent with no policy assigned
    agent_uuid = uuid.uuid4()
    client.post("/api/v1/agents/initAgent", json={
        "agent": {"agent_id": str(agent_uuid), "agent_name": "NoPolicyAgent"},
        "steps": []
    })

    # When: evaluating content for that agent
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm", name="test-step", input="anything", output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: evaluation is safe with no matches
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True
    assert not resp.json()["matches"]


def test_evaluation_empty_policy(client: TestClient):
    """Test that an agent with an empty policy is safe."""
    # Given: an empty policy
    resp = client.put("/api/v1/policies", json={"name": "empty-policy"})
    assert resp.status_code == 200
    policy_id = resp.json()["policy_id"]

    # And: an agent assigned to that policy
    agent_uuid = uuid.uuid4()
    client.post("/api/v1/agents/initAgent", json={
        "agent": {"agent_id": str(agent_uuid), "agent_name": "EmptyPolicyAgent"},
        "steps": []
    })

    client.post(f"/api/v1/agents/{str(agent_uuid)}/policy/{policy_id}")

    # When: evaluating content for that agent
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm", name="test-step", input="anything", output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: evaluation is safe with no matches
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True
    assert not resp.json()["matches"]


def test_evaluation_path_failure(client: TestClient):
    """Test that if path selection fails (returns None), the evaluator handles it gracefully."""
    # Given: A control selecting a non-existent path
    control_data = {
        "description": "Check non-existent field",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input.non_existent_field"}, # Invalid for string input
        "evaluator": {
            "name": "regex",
            "config": {"pattern": ".*"} # Match anything if found
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="PathFailAgent")

    # When: Sending a request
    payload = Step(type="llm", name="test-step", input="some content", output=None)
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=payload,
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: It should remain safe because selector returns None, and RegexEvaluator(None) -> False
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_safe"] is True
    assert len(data["matches"] or []) == 0


def test_evaluation_selector_star_uses_full_step_json(client: TestClient):
    # Given: a control with selector "*" and JSON evaluator
    control_data = {
        "description": "Validate full step JSON",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "*"},
        "evaluator": {"name": "json", "config": {"required_fields": ["type"]}},
        "action": {"decision": "deny"},
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="JsonStarAgent")

    # When: evaluating a valid step payload
    payload = Step(type="llm", name="test-step", input="hello", output=None)
    req = EvaluationRequest(agent_uuid=agent_uuid, step=payload, stage="pre")
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: evaluation is safe (JSON evaluator accepts the full payload)
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True
    assert resp.json()["matches"] is None


def test_evaluation_tool_step_nested(client: TestClient):
    """Test deep path selection into nested tool input."""
    # Given: A control blocking specific nested value in tool input
    control_data = {
        "description": "Block risky nested value",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.config.risk_level"},
        "evaluator": {
            "name": "regex",
            "config": {"pattern": "^critical$"}
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="ToolNestedAgent")

    # Case 1: Safe value
    # When: Sending safe nested value
    safe_payload = Step(type="tool", 
        name="configure_system",
        input={"config": {"risk_level": "low"}},
        output=None
    )
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=safe_payload,
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    
    # Then: Allowed
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: Unsafe value
    # When: Sending unsafe nested value
    unsafe_payload = Step(type="tool", 
        name="configure_system",
        input={"config": {"risk_level": "critical"}},
        output=None
    )
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=unsafe_payload,
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))

    # Then: Denied
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_safe"] is False
    assert data["matches"][0]["control_name"] == control_name


def test_evaluation_deny_precedence(client: TestClient):
    """Test that Deny takes precedence over other controls."""
    # Given: A policy with two controls: one Warn, one Deny
    control_warn = {
        "description": "Warn on keyword",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {"name": "regex", "config": {"pattern": "keyword"}},
        "action": {"decision": "warn"}
    }
    # Use helper to setup agent with first control
    agent_uuid, warn_control_name = create_and_assign_policy(client, control_warn, agent_name="PrecedenceAgent")

    # Create and add second (Deny) control to the same policy
    # Actually, easiest is to fetch the agent's policy ID
    resp = client.get(f"/api/v1/agents/{agent_uuid}/policy")
    policy_id = resp.json()["policy_id"]

    # Create Deny Control
    control_deny = {
        "description": "Deny on keyword",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {"name": "regex", "config": {"pattern": "keyword"}},
        "action": {"decision": "deny"}
    }
    resp = client.put("/api/v1/controls", json={"name": f"deny-control-{uuid.uuid4()}"})
    deny_control_id = resp.json()["control_id"]
    client.put(f"/api/v1/controls/{deny_control_id}/data", json={"data": control_deny})

    # Add Control to Agent's Policy
    client.post(f"/api/v1/policies/{policy_id}/controls/{deny_control_id}")

    # When: Sending request matching "keyword"
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm", name="test-step", input="This has a keyword", output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: Should be Denied (is_safe=False) and have 2 matches
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_safe"] is False
    assert len(data["matches"]) == 2
    actions = {m["action"] for m in data["matches"]}
    assert "deny" in actions
    assert "warn" in actions


def test_evaluation_stage_filtering(client: TestClient):
    """Test that controls are filtered by stage."""
    # Given: A control that only applies to 'post' stage
    control_data = {
        "description": "Post-check only",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "selector": {"path": "output"},
        "evaluator": {"name": "regex", "config": {"pattern": "bad_output"}},
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="StageAgent")

    # When: evaluating at the pre stage
    req_pre = EvaluationRequest(
        agent_uuid=agent_uuid,
        # Even if we provide output, the control shouldn't run in 'pre' stage? 
        # Actually the control says stage='post'. If we send request with stage='pre', it skips.
        step=Step(type="llm", name="test-step", input="bad_output", output="bad_output"),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_pre.model_dump(mode="json"))
    # Then: control does not apply and evaluation is safe
    assert resp.json()["is_safe"] is True
    assert not resp.json()["matches"]

    # When: evaluating at the post stage
    req_post = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm", name="test-step", input="ok", output="bad_output"),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_post.model_dump(mode="json"))
    # Then: control applies and evaluation is unsafe
    assert resp.json()["is_safe"] is False
    assert len(resp.json()["matches"]) > 0


def test_evaluation_step_type_filtering(client: TestClient):
    """Test that controls are filtered by step type (tool vs llm)."""
    # Given: A control that only applies to tool steps
    control_data = {
        "description": "Tool only",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "name"},
        "evaluator": {"name": "regex", "config": {"pattern": "rm_rf"}},
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="AppliesToAgent")

    # When: evaluating an LLM step (control should not apply)
    # Note: LLM steps don't have tool names, but the engine filters by step type.
    req_llm = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm", name="test-step", input="rm_rf", output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_llm.model_dump(mode="json"))
    # Then: evaluation is safe
    assert resp.json()["is_safe"] is True

    # When: evaluating a tool step (control applies)
    req_tool = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="rm_rf", input={}),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_tool.model_dump(mode="json"))
    # Then: evaluation is unsafe
    assert resp.json()["is_safe"] is False


def test_evaluation_denylist_step_name(client: TestClient):
    """Test blocking specific tool steps using a DenyList."""
    # Given: A control blocking "dangerous_tool"
    control_data = {
        "description": "Block dangerous tools",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "name"},
        "evaluator": {
            "name": "list", # Matches if value is IN list (exact match)
            "config": {"values": ["dangerous_tool", "rm_rf"], "match_on": "match"}
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="ToolBlockAgent")

    # When: evaluating a safe tool (not in list)
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="safe_tool", input={}),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    # Then: evaluation is safe
    assert resp.json()["is_safe"] is True

    # When: evaluating a dangerous tool (in list)
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="dangerous_tool", input={}),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))
    # Then: evaluation is unsafe and matches the control
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name
