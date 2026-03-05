"""Tests for force_replace behavior in initAgent endpoint."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_control_server.models import Agent

from .conftest import engine


def test_init_agent_force_replace_default_false_works_normally(client: TestClient):
    """Test that force_replace defaults to false and works normally.

    Given: A new agent
    When: Creating agent without specifying force_replace
    Then: Creates agent normally (force_replace defaults to False)
    """
    # Given: New agent
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name

    # When: Create without force_replace (default)
    resp = client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_name": agent_name,
            "agent_name": agent_name,
            "agent_description": "Test",
            "agent_version": "1.0"
        },
        "steps": []
    })

    # Then: Should succeed
    assert resp.status_code == 200
    assert resp.json()["created"] is True


def test_init_agent_force_replace_false_explicit_works_normally(client: TestClient):
    """Test that explicit force_replace=false works normally.

    Given: A new agent
    When: Creating agent with force_replace=false
    Then: Creates agent normally
    """
    # Given: New agent
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name

    # When: Create with force_replace=false
    resp = client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_name": agent_name,
            "agent_name": agent_name,
            "agent_description": "Test",
            "agent_version": "1.0"
        },
        "steps": [],
        "force_replace": False
    })

    # Then: Should succeed
    assert resp.status_code == 200
    assert resp.json()["created"] is True


def test_init_agent_force_replace_true_on_valid_data_works_normally(client: TestClient):
    """Test that force_replace=true doesn't affect normal updates.

    Given: An existing agent with valid data
    When: Updating with force_replace=true
    Then: Updates normally without data loss
    """
    # Given: Create agent with steps
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    
    resp = client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_name": agent_name,
            "agent_name": agent_name,
            "agent_description": "Test",
            "agent_version": "1.0"
        },
        "steps": [
            {"type": "tool", "name": "tool1", "input_schema": {}, "output_schema": {}},
            {"type": "tool", "name": "tool2", "input_schema": {}, "output_schema": {}}
        ]
    })
    assert resp.status_code == 200

    # When: Update with force_replace=true and add a new step
    resp = client.post("/api/v1/agents/initAgent", json={
        "agent": {
            "agent_name": agent_name,
            "agent_name": agent_name,
            "agent_description": "Updated",
            "agent_version": "2.0"
        },
        "steps": [
            {"type": "tool", "name": "tool1", "input_schema": {}, "output_schema": {}},
            {"type": "tool", "name": "tool2", "input_schema": {}, "output_schema": {}},
            {"type": "tool", "name": "tool3", "input_schema": {}, "output_schema": {}}
        ],
        "force_replace": True
    })

    # Then: Should succeed and all steps should be present
    assert resp.status_code == 200
    get_resp = client.get(f"/api/v1/agents/{agent_name}")
    steps = [s["name"] for s in get_resp.json()["steps"]]
    assert set(steps) == {"tool1", "tool2", "tool3"}


# Note: Testing actual corrupted data scenario requires direct database manipulation
# which is complex in the test environment. The force_replace logic is tested via:
# 1. Normal operation with force_replace=true (above)
# 2. The error path is covered by exception handling in the endpoint
# 
# The corruption scenario would look like:
# 1. Agent data in DB has invalid structure (e.g., steps is a string instead of list)
# 2. initAgent without force_replace → 422 error
# 3. initAgent with force_replace=true → replaces corrupted data
#
# This is difficult to test via HTTP API since the DB corruption must be injected
# externally, but the code path is covered by the implementation.


def test_init_agent_force_replace_recovers_from_corrupted_data(client: TestClient) -> None:
    """Test that force_replace=true replaces corrupted stored data."""
    # Given: an existing agent with corrupted data in the DB
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {
                "agent_name": agent_name,
                "agent_name": agent_name,
                "agent_description": "Test",
                "agent_version": "1.0",
            },
            "steps": [],
        },
    )
    assert resp.status_code == 200

    with Session(engine) as session:
        agent = session.execute(select(Agent).where(Agent.name == agent_name)).scalar_one()
        agent.data = {"steps": "not-a-list"}
        session.commit()

    # When: re-initializing with force_replace=true
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {
                "agent_name": agent_name,
                "agent_name": agent_name,
                "agent_description": "Replaced",
                "agent_version": "2.0",
            },
            "steps": [
                {"type": "tool", "name": "tool_a", "input_schema": {}, "output_schema": {}}
            ],
            "force_replace": True,
        },
    )

    # Then: request succeeds and stored data is replaced
    assert resp.status_code == 200
    get_resp = client.get(f"/api/v1/agents/{agent_name}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["agent"]["agent_description"] == "Replaced"
    assert {s["name"] for s in data["steps"]} == {"tool_a"}
