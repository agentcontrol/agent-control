"""End-to-end tests for evaluation flow."""
import uuid
from fastapi.testclient import TestClient
from agent_control_models import EvaluationRequest, LlmCall, ToolCall
from .utils import create_and_assign_policy


def test_evaluation_flow_deny(client: TestClient):
    # Given: A registered agent with a policy blocking "secret"
    control_data = {
        "description": "Block secret",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "pre",
        "selector": {"path": "input"},
        "evaluator": {
            "plugin": "regex",
            "config": {"pattern": "secret"}
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data)

    # When: Sending a request containing "secret"
    payload = LlmCall(input="This contains a secret", output=None)
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=payload,
        check_stage="pre"
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
    # 1. Register Agent
    agent_uuid = uuid.uuid4()
    client.post("/api/v1/agents/initAgent", json={
        "agent": {"agent_id": str(agent_uuid), "agent_name": "NoPolicyAgent"},
        "tools": []
    })

    # 2. Check Evaluation
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=LlmCall(input="anything", output=None),
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))
    
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True
    assert not resp.json()["matches"]


def test_evaluation_empty_policy(client: TestClient):
    """Test that an agent with an empty policy is safe."""
    # 1. Create Empty Policy
    resp = client.put("/api/v1/policies", json={"name": "empty-policy"})
    assert resp.status_code == 200
    policy_id = resp.json()["policy_id"]

    # 2. Register Agent
    agent_uuid = uuid.uuid4()
    client.post("/api/v1/agents/initAgent", json={
        "agent": {"agent_id": str(agent_uuid), "agent_name": "EmptyPolicyAgent"},
        "tools": []
    })

    # 3. Assign Policy
    client.post(f"/api/v1/agents/{str(agent_uuid)}/policy/{policy_id}")

    # 4. Check Evaluation
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=LlmCall(input="anything", output=None),
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))
    
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True
    assert not resp.json()["matches"]


def test_evaluation_path_failure(client: TestClient):
    """Test that if path selection fails (returns None), the evaluator handles it gracefully."""
    # Given: A control selecting a non-existent path
    control_data = {
        "description": "Check non-existent field",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "pre",
        "selector": {"path": "input.non_existent_field"}, # Invalid for string input
        "evaluator": {
            "plugin": "regex",
            "config": {"pattern": ".*"} # Match anything if found
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="PathFailAgent")

    # When: Sending a request
    payload = LlmCall(input="some content", output=None)
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=payload,
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: It should remain safe because selector returns None, and RegexEvaluator(None) -> False
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_safe"] is True
    assert len(data["matches"] or []) == 0


def test_evaluation_tool_call_nested(client: TestClient):
    """Test deep path selection into nested tool arguments."""
    # Given: A control blocking specific nested value in tool arguments
    control_data = {
        "description": "Block risky nested value",
        "enabled": True,
        "applies_to": "tool_call",
        "check_stage": "pre",
        "selector": {"path": "arguments.config.risk_level"},
        "evaluator": {
            "plugin": "regex",
            "config": {"pattern": "^critical$"}
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="ToolNestedAgent")

    # Case 1: Safe value
    # When: Sending safe nested value
    safe_payload = ToolCall(
        tool_name="configure_system",
        arguments={"config": {"risk_level": "low"}},
        output=None
    )
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=safe_payload,
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    
    # Then: Allowed
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: Unsafe value
    # When: Sending unsafe nested value
    unsafe_payload = ToolCall(
        tool_name="configure_system",
        arguments={"config": {"risk_level": "critical"}},
        output=None
    )
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=unsafe_payload,
        check_stage="pre"
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
        "applies_to": "llm_call",
        "check_stage": "pre",
        "selector": {"path": "input"},
        "evaluator": {"plugin": "regex", "config": {"pattern": "keyword"}},
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
        "applies_to": "llm_call",
        "check_stage": "pre",
        "selector": {"path": "input"},
        "evaluator": {"plugin": "regex", "config": {"pattern": "keyword"}},
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
        payload=LlmCall(input="This has a keyword", output=None),
        check_stage="pre"
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


def test_evaluation_check_stage_filtering(client: TestClient):
    """Test that controls are filtered by check_stage."""
    # Given: A control that only applies to 'post' stage
    control_data = {
        "description": "Post-check only",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "post",
        "selector": {"path": "output"},
        "evaluator": {"plugin": "regex", "config": {"pattern": "bad_output"}},
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="StageAgent")

    # 1. Pre-check (Should be Safe even if pattern exists in input/output placeholder)
    req_pre = EvaluationRequest(
        agent_uuid=agent_uuid,
        # Even if we provide output, the control shouldn't run in 'pre' stage? 
        # Actually the control says check_stage='post'. If we send request with check_stage='pre', it skips.
        payload=LlmCall(input="bad_output", output="bad_output"),
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_pre.model_dump(mode="json"))
    assert resp.json()["is_safe"] is True
    assert not resp.json()["matches"]

    # 2. Post-check (Should be Unsafe)
    req_post = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=LlmCall(input="ok", output="bad_output"),
        check_stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_post.model_dump(mode="json"))
    assert resp.json()["is_safe"] is False
    assert len(resp.json()["matches"]) > 0


def test_evaluation_applies_to_filtering(client: TestClient):
    """Test that controls are filtered by applies_to (tool vs llm)."""
    # Given: A control that only applies to 'tool_call'
    control_data = {
        "description": "Tool only",
        "enabled": True,
        "applies_to": "tool_call",
        "check_stage": "pre",
        "selector": {"path": "tool_name"},
        "evaluator": {"plugin": "regex", "config": {"pattern": "rm_rf"}},
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="AppliesToAgent")

    # 1. LLM Call (Should be Safe even if content matches)
    # Note: LLM call doesn't have tool_name, but we want to ensure the control doesn't even TRY to run (which might error or return None)
    # But specifically, the engine filters by applies_to.
    req_llm = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=LlmCall(input="rm_rf", output=None),
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_llm.model_dump(mode="json"))
    assert resp.json()["is_safe"] is True

    # 2. Tool Call (Should be Unsafe)
    req_tool = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=ToolCall(tool_name="rm_rf", arguments={}),
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_tool.model_dump(mode="json"))
    assert resp.json()["is_safe"] is False


def test_evaluation_denylist_tool_name(client: TestClient):
    """Test blocking specific tools using a DenyList."""
    # Given: A control blocking "dangerous_tool"
    control_data = {
        "description": "Block dangerous tools",
        "enabled": True,
        "applies_to": "tool_call",
        "check_stage": "pre",
        "selector": {"path": "tool_name"},
        "evaluator": {
            "plugin": "list", # Matches if value is IN list (exact match)
            "config": {"values": ["dangerous_tool", "rm_rf"], "match_on": "match"}
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="ToolBlockAgent")

    # 1. Safe Tool (Not in list) -> Allowed
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=ToolCall(tool_name="safe_tool", arguments={}),
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    assert resp.json()["is_safe"] is True

    # 2. Dangerous Tool (In list) -> Denied
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=ToolCall(tool_name="dangerous_tool", arguments={}),
        check_stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name
