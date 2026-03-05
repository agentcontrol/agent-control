import json
import logging
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from agent_control_server.config import db_config
from agent_control_server.models import Agent

# Create sync engine for raw database queries in tests
engine = create_engine(db_config.get_url(), echo=False)


def make_agent_payload(
    agent_name: str | None = None,
    name: str = "testagent0001",
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_name = name if name != "testagent0001" else (agent_name or f"agent-{uuid.uuid4().hex[:12]}")
    canonical_name = resolved_name.lower().replace(" ", "-")
    if len(canonical_name) < 10:
        canonical_name = f"{canonical_name}-agent".replace("--", "-")
    if steps is None:
        steps = [
            {
                "type": "tool",
                "name": "tool_a",
                "input_schema": {"a": "int"},
                "output_schema": {"ok": "bool"},
            }
        ]
    return {
        "agent": {
            "agent_name": canonical_name,
            "agent_name": canonical_name,
            "agent_description": "desc",
            "agent_version": "1.0",
            "agent_metadata": {"env": "test"},
        },
        "steps": steps,
    }


def test_init_agent_route_exists(app: FastAPI) -> None:
    # Given: an application router
    paths = {getattr(route, "path", None) for route in app.router.routes}
    # When: inspecting registered paths
    # (computation done above to gather all paths)
    # Then: initAgent and agent retrieval endpoints are present
    assert "/api/v1/agents/initAgent" in paths
    assert "/api/v1/agents/{agent_name}" in paths


def test_init_agent_creates_and_gets_agent(client: TestClient) -> None:
    # Given: an init payload
    payload = make_agent_payload()
    # When: initializing the agent
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    # Then: the agent is created and controls are empty
    assert body["created"] is True
    assert body["controls"] == []

    agent_name = payload["agent"]["agent_name"]
    # When: retrieving the agent by id
    resp2 = client.get(f"/api/v1/agents/{agent_name}")
    assert resp2.status_code == 200
    data = resp2.json()
    # Then: stored agent fields match the request
    assert data["agent"]["agent_name"] == payload["agent"]["agent_name"]
    assert {s["name"] for s in data["steps"]} == {payload["steps"][0]["name"]}


def test_agent_endpoints_normalize_mixed_case_agent_name(client: TestClient) -> None:
    # Given: an agent registered with mixed-case identifier
    mixed_case_name = "Agent-PathNorm01"
    payload = {
        "agent": {
            "agent_name": mixed_case_name,
            "agent_description": "desc",
            "agent_version": "1.0",
        },
        "steps": [],
    }
    init_resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert init_resp.status_code == 200

    # When: hitting path-based agent endpoints using mixed-case path params
    get_resp = client.get(f"/api/v1/agents/{mixed_case_name}")
    assert get_resp.status_code == 200
    assert get_resp.json()["agent"]["agent_name"] == mixed_case_name.lower()

    policy_id = _create_policy(client)
    set_policy_resp = client.post(f"/api/v1/agents/{mixed_case_name}/policy/{policy_id}")
    assert set_policy_resp.status_code == 200

    get_policy_resp = client.get(f"/api/v1/agents/{mixed_case_name}/policy")
    assert get_policy_resp.status_code == 200
    assert get_policy_resp.json()["policy_id"] == policy_id

    controls_resp = client.get(f"/api/v1/agents/{mixed_case_name}/controls")
    assert controls_resp.status_code == 200

    evaluators_resp = client.get(f"/api/v1/agents/{mixed_case_name}/evaluators")
    assert evaluators_resp.status_code == 200

    patch_resp = client.patch(
        f"/api/v1/agents/{mixed_case_name}",
        json={"remove_steps": [], "remove_evaluators": []},
    )
    assert patch_resp.status_code == 200

    delete_policy_resp = client.delete(f"/api/v1/agents/{mixed_case_name}/policy")
    assert delete_policy_resp.status_code == 200


def test_init_agent_nameempotent_same_steps(client: TestClient) -> None:
    # Given: an init payload
    payload = make_agent_payload()
    # When: initializing the agent the first time
    r1 = client.post("/api/v1/agents/initAgent", json=payload)
    assert r1.status_code == 200
    # Then: it is created
    assert r1.json()["created"] is True

    # When: initializing the same payload again
    r2 = client.post("/api/v1/agents/initAgent", json=payload)
    assert r2.status_code == 200
    # Then: it is not created again (idempotent)
    assert r2.json()["created"] is False


def test_init_agent_updates_metadata_on_reinit(client: TestClient) -> None:
    """Test that agent metadata is refreshed on re-registration.

    Given: An existing agent with initial metadata
    When: Re-initializing with updated description/version
    Then: The new metadata is persisted
    """
    # Given: create initial agent
    agent_name = "metadatatestagent"
    initial_payload = {
        "agent": {
            "agent_name": agent_name,
            "agent_description": "Original description",
            "agent_version": "1.0.0",
            "agent_metadata": {"env": "dev"},
        },
        "steps": [],
    }
    r1 = client.post("/api/v1/agents/initAgent", json=initial_payload)
    assert r1.status_code == 200
    assert r1.json()["created"] is True

    # When: re-init with updated metadata
    updated_payload = {
        "agent": {
            "agent_name": agent_name,
            "agent_description": "Updated description",
            "agent_version": "2.0.0",
            "agent_metadata": {"env": "prod", "new_field": "value"},
        },
        "steps": [],
    }
    r2 = client.post("/api/v1/agents/initAgent", json=updated_payload)
    assert r2.status_code == 200
    assert r2.json()["created"] is False

    # Then: verify metadata is updated
    get_resp = client.get(f"/api/v1/agents/{agent_name}")
    assert get_resp.status_code == 200
    agent_data = get_resp.json()["agent"]
    assert agent_data["agent_description"] == "Updated description"
    assert agent_data["agent_version"] == "2.0.0"
    assert agent_data["agent_metadata"] == {"env": "prod", "new_field": "value"}


def test_init_agent_adds_new_step(client: TestClient) -> None:
    # Given: an agent id and base payload
    agent_name = str(uuid.uuid4())
    base = make_agent_payload(agent_name=agent_name)
    # When: initializing the agent
    r1 = client.post("/api/v1/agents/initAgent", json=base)
    assert r1.status_code == 200

    # When: sending an additional step
    steps = base["steps"] + [
        {
            "type": "tool",
            "name": "tool_b",
            "input_schema": {"b": "str"},
            "output_schema": {"ok": "bool"},
        }
    ]
    r2 = client.post(
        "/api/v1/agents/initAgent",
        json=make_agent_payload(agent_name=agent_name, steps=steps),
    )
    assert r2.status_code == 200
    # Then: the agent is not newly created
    assert r2.json()["created"] is False

    # When: fetching the agent
    g = client.get(f"/api/v1/agents/{agent_name}")
    assert g.status_code == 200
    names = {s["name"] for s in g.json()["steps"]}
    # Then: both steps are present
    assert names == {"tool_a", "tool_b"}


def test_init_agent_overwrites_step_on_signature_change(client: TestClient) -> None:
    # Given: a base payload for an agent
    agent_name = str(uuid.uuid4())
    base = make_agent_payload(agent_name=agent_name)
    # When: initializing the agent
    r1 = client.post("/api/v1/agents/initAgent", json=base)
    assert r1.status_code == 200

    # When: updating tool_a schema
    changed = make_agent_payload(
        agent_name=agent_name,
        steps=[
            {
                "type": "tool",
                "name": "tool_a",
                "input_schema": {"a": "str"},  # changed type
                "output_schema": {"ok": "bool"},
            }
        ],
    )
    r2 = client.post("/api/v1/agents/initAgent", json=changed)
    # Then: schema conflict error is returned (schema changes are now rejected)
    assert r2.status_code == 409
    body = r2.json()
    assert body["error_code"] == "SCHEMA_INCOMPATIBLE"
    assert "schema conflict" in body["detail"].lower()


def test_get_agent_returns_evaluators(client: TestClient) -> None:
    """Test that GET /agents/{id} returns evaluators."""
    # Given: an agent with evaluators
    agent_name = str(uuid.uuid4())
    payload = make_agent_payload(agent_name=agent_name)
    payload["evaluators"] = [
        {"name": "eval-a", "description": "First", "config_schema": {}},
        {"name": "eval-b", "description": "Second", "config_schema": {"type": "object"}},
    ]
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 200

    # When: fetching the agent
    get_resp = client.get(f"/api/v1/agents/{agent_name}")
    # Then: evaluators are included in the response
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert "evaluators" in data
    assert len(data["evaluators"]) == 2
    names = {e["name"] for e in data["evaluators"]}
    assert names == {"eval-a", "eval-b"}


def test_get_agent_not_found(client: TestClient) -> None:
    # Given: a random (missing) agent id
    missing = str(uuid.uuid4())
    # When: fetching the agent
    resp = client.get(f"/api/v1/agents/{missing}")
    # Then: a 404 is returned
    assert resp.status_code == 404


def test_init_agent_logs_warning_on_bad_existing_data(client: TestClient, caplog) -> None:
    # Given: an existing agent
    payload = make_agent_payload()
    r1 = client.post("/api/v1/agents/initAgent", json=payload)
    assert r1.status_code == 200

    # When: corrupting the stored data so parsing fails
    with Session(engine) as session:
        agent = session.execute(
            select(Agent).where(Agent.name == payload["agent"]["agent_name"])
        ).scalar_one()
        agent.data = {"foo": "bar"}
        session.commit()

    # When: re-initializing with the same payload (without force_replace)
    logger_name = "agent_control_server.endpoints.agents"
    with caplog.at_level(logging.ERROR, logger=logger_name):
        r2 = client.post("/api/v1/agents/initAgent", json=payload)
        # Then: a 422 error is returned (RFC 7807 format)
        assert r2.status_code == 422
        response_data = r2.json()
        assert "corrupted data" in response_data.get("detail", "").lower()
        # Check hint contains force_replace suggestion
        assert "force_replace" in response_data.get("hint", "").lower()
        assert response_data["errors"][0]["message"] == (
            "Stored agent data is corrupted and cannot be parsed."
        )
        assert "ValidationError" not in response_data["errors"][0]["message"]
        # Then: an error is logged about parse failure
        messages = [rec.getMessage() for rec in caplog.records]
        assert any("Failed to parse existing agent data" in m for m in messages)


import uuid

def _create_policy(client: TestClient) -> int:
    # Helper: create a policy via API and return id
    name = f"pol-{uuid.uuid4()}"
    resp = client.put("/api/v1/policies", json={"name": name})
    assert resp.status_code == 200
    pid = resp.json()["policy_id"]
    assert isinstance(pid, int)
    return pid


def test_set_agent_policy_first_time(client: TestClient) -> None:
    # Given: a created policy and agent
    policy_id = _create_policy(client)
    payload = make_agent_payload()
    r = client.post("/api/v1/agents/initAgent", json=payload)
    assert r.status_code == 200
    agent_name = payload["agent"]["agent_name"]

    # When: assigning policy the first time
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    # Then: success and no old policy
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["old_policy_id"] is None


def test_get_agent_policy_after_assignment(client: TestClient) -> None:
    # Given: an agent with a policy assigned
    policy_id = _create_policy(client)
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)
    agent_name = payload["agent"]["agent_name"]
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # When: retrieving policy
    resp = client.get(f"/api/v1/agents/{agent_name}/policy")
    # Then: we see the assigned policy id
    assert resp.status_code == 200
    assert resp.json()["policy_id"] == policy_id


def test_reassign_agent_policy_returns_old_id(client: TestClient) -> None:
    # Given: an agent with an existing policy
    first = _create_policy(client)
    second = _create_policy(client)
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)
    agent_name = payload["agent"]["agent_name"]
    client.post(f"/api/v1/agents/{agent_name}/policy/{first}")

    # When: reassigning to another policy
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{second}")
    # Then: success and old_policy_id equals the first policy id
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["old_policy_id"] == first


def test_delete_agent_policy_then_get_404(client: TestClient) -> None:
    # Given: an agent with a policy assigned
    policy_id = _create_policy(client)
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)
    agent_name = payload["agent"]["agent_name"]
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # When: removing the policy association
    del_resp = client.delete(f"/api/v1/agents/{agent_name}/policy")
    # Then: deletion success
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # When: fetching policy after deletion
    get_resp = client.get(f"/api/v1/agents/{agent_name}/policy")
    # Then: not found
    assert get_resp.status_code == 404


def test_set_policy_agent_not_found_returns_404(client: TestClient) -> None:
    # Given: a policy id and a random agent uuid
    policy_id = _create_policy(client)
    missing_agent = str(uuid.uuid4())

    # When: assigning to missing agent
    resp = client.post(f"/api/v1/agents/{missing_agent}/policy/{policy_id}")
    # Then: 404
    assert resp.status_code == 404


def test_set_policy_not_found_returns_404(client: TestClient) -> None:
    # Given: an agent and a bogus policy id
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)
    agent_name = payload["agent"]["agent_name"]
    bogus_policy = "999999999"

    # When: assigning a non-existent policy
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{bogus_policy}")
    # Then: 404
    assert resp.status_code == 404


def test_list_agent_controls_no_policy_returns_empty(client: TestClient) -> None:
    # Given: an agent without a policy
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)
    agent_name = payload["agent"]["agent_name"]

    # When: listing controls
    r = client.get(f"/api/v1/agents/{agent_name}/controls")
    # Then: empty list
    assert r.status_code == 200
    assert r.json()["controls"] == []


def test_list_agent_controls_with_policy(client: TestClient) -> None:
    # Given: an agent with a policy containing one control set and one control
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)
    agent_name = payload["agent"]["agent_name"]

    # Create policy, control, and wire them
    pol_name = f"pol-{uuid.uuid4()}"
    pol = client.put("/api/v1/policies", json={"name": pol_name})
    policy_id = pol.json()["policy_id"]

    ctl_name = f"control-{uuid.uuid4()}"
    ctl = client.put("/api/v1/controls", json={"name": ctl_name})
    control_id = ctl.json()["control_id"]

    # Set control data
    from .utils import VALID_CONTROL_PAYLOAD
    data_payload = VALID_CONTROL_PAYLOAD
    client.put(f"/api/v1/controls/{control_id}/data", json={"data": data_payload})

    # Associate control -> policy; assign policy to agent
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # When: listing controls
    r = client.get(f"/api/v1/agents/{agent_name}/controls")
    # Then: contains our control serialized via API model
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("controls"), list)
    # Verify control data is present and matches description
    assert any(
        item.get("control", {}).get("description") == data_payload["description"] 
        for item in body["controls"]
    )


def test_list_agent_controls_agent_not_found_404(client: TestClient) -> None:
    # Given: random agent id
    missing = str(uuid.uuid4())
    # When: requesting
    r = client.get(f"/api/v1/agents/{missing}/controls")
    # Then: 404
    assert r.status_code == 404


def test_init_agent_rejects_invalid_agent_name(client: TestClient) -> None:
    # Given: a payload with an invalid agent_name
    payload = {
        "agent": {
            "agent_name": "short",
            "agent_description": "desc",
            "agent_version": "1.0",
        },
        "steps": [],
    }
    # When: calling initAgent
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    # Then: a 422 validation error is returned
    assert resp.status_code == 422


# =============================================================================
# List Agents Endpoint Tests
# =============================================================================


def test_list_agents_empty(client: TestClient) -> None:
    """Test listing agents when none exist returns empty list."""
    # Given: no agents are registered
    # When: listing agents with no agents created
    resp = client.get("/api/v1/agents")
    # Then: returns empty list with zero total
    assert resp.status_code == 200
    body = resp.json()
    assert body["agents"] == []
    assert body["pagination"]["total"] == 0
    assert body["pagination"]["limit"] == 20
    assert body["pagination"]["has_more"] is False
    assert body["pagination"]["next_cursor"] is None


def test_list_agents_returns_created_agents(client: TestClient) -> None:
    """Test listing agents returns created agents with correct summaries."""
    # Given: two agents with different steps/evaluators
    payload1 = make_agent_payload(name="agent-one-01")
    payload1["evaluators"] = [
        {"name": "eval-1", "description": "Test", "config_schema": {}},
    ]
    r1 = client.post("/api/v1/agents/initAgent", json=payload1)
    assert r1.status_code == 200

    payload2 = make_agent_payload(name="agent-two-02")
    payload2["steps"] = [
        {"type": "tool", "name": "tool_x", "input_schema": {}, "output_schema": {}},
        {"type": "tool", "name": "tool_y", "input_schema": {}, "output_schema": {}},
    ]
    r2 = client.post("/api/v1/agents/initAgent", json=payload2)
    assert r2.status_code == 200

    # When: listing agents
    resp = client.get("/api/v1/agents")
    # Then: both agents are returned
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["total"] == 2
    assert len(body["agents"]) == 2

    # Verify agent summaries contain correct data
    agent_map = {a["agent_name"]: a for a in body["agents"]}

    assert "agent-one-01" in agent_map
    agent1 = agent_map["agent-one-01"]
    assert agent1["agent_name"] == "agent-one-01"
    assert agent1["step_count"] == 1  # from make_agent_payload
    assert agent1["evaluator_count"] == 1
    assert agent1["policy_ids"] == []

    assert "agent-two-02" in agent_map
    agent2 = agent_map["agent-two-02"]
    assert agent2["agent_name"] == "agent-two-02"
    assert agent2["step_count"] == 2
    assert agent2["evaluator_count"] == 0
    assert agent2["policy_ids"] == []


def test_list_agents_with_policy(client: TestClient) -> None:
    """Test that list agents shows policy_ids when assigned."""
    # Given: an agent with a policy assigned
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)
    agent_name = payload["agent"]["agent_name"]

    policy_id = _create_policy(client)
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # When: listing agents
    resp = client.get("/api/v1/agents")
    # Then: the agent shows policy_ids
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["agents"]) == 1
    assert body["agents"][0]["policy_ids"] == [policy_id]


def test_list_agents_pagination(client: TestClient) -> None:
    """Test cursor-based pagination works correctly."""
    # Given: 5 agents
    agent_names = []
    for i in range(5):
        agent_name = str(uuid.uuid4())
        agent_names.append(agent_name)
        payload = make_agent_payload(agent_name=agent_name, name=f"Agent {i}")
        r = client.post("/api/v1/agents/initAgent", json=payload)
        assert r.status_code == 200

    # When: requesting first page with limit=2
    resp = client.get("/api/v1/agents?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    # Then: pagination metadata indicates more pages
    assert body["pagination"]["total"] == 5
    assert len(body["agents"]) == 2
    assert body["pagination"]["limit"] == 2
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["next_cursor"] is not None

    # When: requesting next page using cursor
    cursor = body["pagination"]["next_cursor"]
    resp2 = client.get(f"/api/v1/agents?limit=2&cursor={cursor}")
    assert resp2.status_code == 200
    body2 = resp2.json()
    # Then: second page returns two more agents
    assert body2["pagination"]["total"] == 5
    assert len(body2["agents"]) == 2
    assert body2["pagination"]["has_more"] is True

    # When: requesting third page (should have 1 agent left)
    cursor2 = body2["pagination"]["next_cursor"]
    resp3 = client.get(f"/api/v1/agents?limit=2&cursor={cursor2}")
    assert resp3.status_code == 200
    body3 = resp3.json()
    # Then: last page returns remaining agent and ends pagination
    assert body3["pagination"]["total"] == 5
    assert len(body3["agents"]) == 1
    assert body3["pagination"]["has_more"] is False
    assert body3["pagination"]["next_cursor"] is None


def test_list_agents_accepts_mixed_case_cursor(client: TestClient) -> None:
    # Given: three agents to paginate
    for i in range(3):
        payload = make_agent_payload(name=f"agent-cursor-{i:02d}")
        resp = client.post("/api/v1/agents/initAgent", json=payload)
        assert resp.status_code == 200

    first_page = client.get("/api/v1/agents?limit=1")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert first_body["pagination"]["has_more"] is True
    assert first_body["pagination"]["next_cursor"] is not None

    mixed_case_cursor = str(first_body["pagination"]["next_cursor"]).upper()

    # When: requesting second page with mixed-case cursor
    second_page = client.get(f"/api/v1/agents?limit=1&cursor={mixed_case_cursor}")
    assert second_page.status_code == 200
    second_body = second_page.json()

    # Then: cursor is normalized and pagination advances
    assert len(second_body["agents"]) == 1
    assert second_body["agents"][0]["agent_name"] != first_body["agents"][0]["agent_name"]


def test_list_agents_limit_clamping(client: TestClient) -> None:
    """Test that limit is clamped to valid range."""
    # Given: one agent
    payload = make_agent_payload()
    client.post("/api/v1/agents/initAgent", json=payload)

    # When: requesting with limit > 100
    resp = client.get("/api/v1/agents?limit=200")
    assert resp.status_code == 200
    body = resp.json()
    # Then: limit is clamped to 100
    assert body["pagination"]["limit"] == 100

    # When: requesting with limit < 1
    resp2 = client.get("/api/v1/agents?limit=0")
    assert resp2.status_code == 200
    body2 = resp2.json()
    # Then: limit is clamped to 1
    assert body2["pagination"]["limit"] == 1
