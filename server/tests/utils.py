"""Test utilities for server tests."""
import uuid
from typing import Any
from fastapi.testclient import TestClient


VALID_CONTROL_PAYLOAD = {
    "description": "Valid Control",
    "enabled": True,
    "execution": "server",
    "scope": {"step_types": ["llm"], "stages": ["pre"]},
    "selector": {"path": "input"},
    "evaluator": {"name": "regex", "config": {"pattern": "x"}},
    "action": {"decision": "deny"}
}


def create_and_assign_control(
    client: TestClient,
    control_config: dict[str, Any] | None = None,
    agent_name: str = "MyTestAgent",
) -> tuple[uuid.UUID, str]:
    """Helper to setup Agent -> Control direct association.

    Args:
        client: Test client
        control_config: Optional control configuration. If None, uses VALID_CONTROL_PAYLOAD.
        agent_name: Name for the test agent

    Returns:
        tuple: (agent_uuid, control_name)
    """
    if control_config is None:
        control_config = VALID_CONTROL_PAYLOAD.copy()

    # 1. Create Control
    control_name = f"control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": control_name})
    assert resp.status_code == 200
    control_id = resp.json()["control_id"]

    # 2. Configure Control
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": control_config})
    assert resp.status_code == 200

    # 3. Register Agent
    agent_uuid = uuid.uuid4()
    resp = client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_id": str(agent_uuid),
            "agent_name": agent_name
        },
        "steps": []
    })
    assert resp.status_code == 200

    # 4. Assign Control to Agent directly
    resp = client.post(f"/api/v1/agents/{str(agent_uuid)}/controls/{control_id}")
    assert resp.status_code == 200

    return agent_uuid, control_name
