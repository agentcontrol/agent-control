"""Test utilities for server tests."""
import uuid
from typing import Any
from fastapi.testclient import TestClient


VALID_CONTROL_PAYLOAD = {
    "description": "Valid Control",
    "enabled": True,
    "applies_to": "llm_call",
    "check_stage": "pre",
    "selector": {"path": "input"},
    "evaluator": {"plugin": "regex", "config": {"pattern": "x"}},
    "action": {"decision": "deny"}
}

def create_and_assign_policy(client: TestClient, control_config: dict[str, Any] | None = None, agent_name: str = "MyTestAgent") -> tuple[uuid.UUID, str]:
    """Helper to setup Agent -> Policy -> ControlSet -> Control hierarchy.
    
    Args:
        control_config: Optional control configuration. If None, uses VALID_CONTROL_PAYLOAD.
    
    Returns:
        tuple: (agent_uuid, control_name)
    """
    if control_config is None:
        control_config = VALID_CONTROL_PAYLOAD.copy()
    control_name = f"control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": control_name})
    assert resp.status_code == 200
    control_id = resp.json()["control_id"]

    # 1.1 Configure Control
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": control_config})
    assert resp.status_code == 200

    # 2. Create Control Set
    control_set_name = f"cs-{uuid.uuid4()}"
    resp = client.put("/api/v1/control-sets", json={"name": control_set_name})
    assert resp.status_code == 200
    control_set_id = resp.json()["control_set_id"]
    
    client.post(f"/api/v1/control-sets/{control_set_id}/controls/{control_id}")

    # 3. Create Policy
    policy_name = f"policy-{uuid.uuid4()}"
    resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert resp.status_code == 200
    policy_id = resp.json()["policy_id"]
    
    client.post(f"/api/v1/policies/{policy_id}/control_sets/{control_set_id}")

    # 4. Register Agent
    agent_uuid = uuid.uuid4()
    resp = client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_id": str(agent_uuid),
            "agent_name": agent_name
        },
        "tools": []
    })
    assert resp.status_code == 200

    # 5. Assign Policy
    client.post(f"/api/v1/agents/{str(agent_uuid)}/policy/{policy_id}")
    
    return agent_uuid, control_name
