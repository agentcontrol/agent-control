"""Integration tests for the full policy → control chain."""

import uuid

from fastapi.testclient import TestClient


def _create_agent(client: TestClient, name: str | None = None) -> tuple[str, str]:
    """Helper: Create an agent and return (agent_name, agent_name)."""
    agent_name = (name or f"agent-{uuid.uuid4().hex[:12]}").lower()
    if len(agent_name) < 10:
        agent_name = f"{agent_name}-agent".replace("--", "-")
    payload = {
        "agent": {
            "agent_name": agent_name,
            "agent_description": "test",
            "agent_version": "1.0",
            "agent_metadata": {},
        },
        "steps": [],
    }
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 200
    return agent_name, agent_name


def _create_policy(client: TestClient, name: str | None = None) -> int:
    """Helper: Create a policy and return policy_id."""
    policy_name = name or f"policy-{uuid.uuid4()}"
    resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert resp.status_code == 200
    return resp.json()["policy_id"]


from .utils import VALID_CONTROL_PAYLOAD


def _create_control(client: TestClient, name: str | None = None, data: dict | None = None) -> int:
    """Helper: Create a control and return control_id."""
    control_name = name or f"control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": control_name})
    assert resp.status_code == 200
    control_id = resp.json()["control_id"]

    # Always set valid data, using name/data in description for traceability
    payload = VALID_CONTROL_PAYLOAD.copy()
    payload["description"] = f"Name: {control_name}, Data: {data}"

    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})
    assert resp.status_code == 200

    return control_id


def test_agent_gets_controls_from_policy(client: TestClient) -> None:
    """Agent should see all controls from its policy."""
    # Given: Agent with policy containing 6 controls
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)

    # Create 6 controls
    control_ids = []
    for i in range(6):
        control_data = {"index": i, "level": i * 10}
        control_id = _create_control(client, f"control-{i}", control_data)
        control_ids.append(control_id)
        # Associate control with policy
        resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
        assert resp.status_code == 200

    # Assign policy to agent
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    assert resp.status_code == 200

    # When: Get agent's controls
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert resp.status_code == 200
    controls = resp.json()["controls"]

    # Then: Agent sees all 6 controls
    assert len(controls) == 6

    # Verify all control IDs are present
    received_ids = {r["id"] for r in controls}
    assert received_ids == set(control_ids)


def test_agent_controls_update_when_control_added_to_policy(client: TestClient) -> None:
    """Adding a control to policy should make it visible to agents."""
    # Given: Agent → Policy → 2 controls
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)

    control_1_id = _create_control(client, "control-1", {"id": 1})
    control_2_id = _create_control(client, "control-2", {"id": 2})

    client.post(f"/api/v1/policies/{policy_id}/controls/{control_1_id}")
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_2_id}")
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # Verify initial state: 2 controls
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert len(resp.json()["controls"]) == 2

    # When: Add 3 more controls to the policy
    control_3_id = _create_control(client, "control-3", {"id": 3})
    control_4_id = _create_control(client, "control-4", {"id": 4})
    control_5_id = _create_control(client, "control-5", {"id": 5})

    resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_3_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_4_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_5_id}")
    assert resp.status_code == 200

    # Then: Agent now sees 5 controls total
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    controls = resp.json()["controls"]
    assert len(controls) == 5

    control_ids = {r["id"] for r in controls}
    assert control_ids == {control_1_id, control_2_id, control_3_id, control_4_id, control_5_id}


def test_switching_agent_policy_changes_controls(client: TestClient) -> None:
    """Switching agent's policy should completely change its controls."""
    # Given: Two policies with different controls
    agent_name, _ = _create_agent(client)

    # Policy A with controls {1, 2}
    policy_a_id = _create_policy(client, "policy-a")
    control_1_id = _create_control(client, "control-1", {"policy": "A", "id": 1})
    control_2_id = _create_control(client, "control-2", {"policy": "A", "id": 2})
    client.post(f"/api/v1/policies/{policy_a_id}/controls/{control_1_id}")
    client.post(f"/api/v1/policies/{policy_a_id}/controls/{control_2_id}")

    # Policy B with controls {3, 4}
    policy_b_id = _create_policy(client, "policy-b")
    control_3_id = _create_control(client, "control-3", {"policy": "B", "id": 3})
    control_4_id = _create_control(client, "control-4", {"policy": "B", "id": 4})
    client.post(f"/api/v1/policies/{policy_b_id}/controls/{control_3_id}")
    client.post(f"/api/v1/policies/{policy_b_id}/controls/{control_4_id}")

    # Assign policy A to agent
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_a_id}")
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    controls_a = resp.json()["controls"]
    assert len(controls_a) == 2
    assert {r["id"] for r in controls_a} == {control_1_id, control_2_id}

    # When: Switch to policy B
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_b_id}")
    assert resp.status_code == 200

    # Then: Agent's controls change completely
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    controls_b = resp.json()["controls"]
    assert len(controls_b) == 2
    assert {r["id"] for r in controls_b} == {control_3_id, control_4_id}


def test_removing_agent_policy_clears_controls(client: TestClient) -> None:
    """Removing policy from agent should result in empty controls list."""
    # Given: Agent with policy that has controls
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)
    control_id = _create_control(client, "control-1", {"id": 1})

    client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # Verify agent has controls
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert len(resp.json()["controls"]) > 0

    # When: Remove policy from agent
    resp = client.delete(f"/api/v1/agents/{agent_name}/policy")
    assert resp.status_code == 200

    # Then: Agent returns empty controls list
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert resp.status_code == 200
    assert resp.json()["controls"] == []


def test_removing_control_from_policy_removes_from_agent(client: TestClient) -> None:
    """Removing control from policy should remove it from agent."""
    # Given: Agent → Policy → 4 controls
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)

    control_1_id = _create_control(client, "control-1", {"id": 1})
    control_2_id = _create_control(client, "control-2", {"id": 2})
    control_3_id = _create_control(client, "control-3", {"id": 3})
    control_4_id = _create_control(client, "control-4", {"id": 4})

    client.post(f"/api/v1/policies/{policy_id}/controls/{control_1_id}")
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_2_id}")
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_3_id}")
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_4_id}")
    client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # Verify initial state: 4 controls
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert len(resp.json()["controls"]) == 4

    # When: Remove 2 controls from policy
    resp = client.delete(f"/api/v1/policies/{policy_id}/controls/{control_1_id}")
    assert resp.status_code == 200
    resp = client.delete(f"/api/v1/policies/{policy_id}/controls/{control_2_id}")
    assert resp.status_code == 200

    # Then: Agent sees 2 remaining controls
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    controls = resp.json()["controls"]
    assert len(controls) == 2
    assert {r["id"] for r in controls} == {control_3_id, control_4_id}


def test_multiple_agents_same_policy(client: TestClient) -> None:
    """Multiple agents with same policy should all see the same controls."""
    # Given: 2 agents assigned to same policy
    agent_1_id, _ = _create_agent(client, "agent-1")
    agent_2_id, _ = _create_agent(client, "agent-2")

    policy_id = _create_policy(client)

    control_1_id = _create_control(client, "control-1", {"id": 1})
    control_2_id = _create_control(client, "control-2", {"id": 2})

    client.post(f"/api/v1/policies/{policy_id}/controls/{control_1_id}")
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_2_id}")

    # Assign same policy to both agents
    client.post(f"/api/v1/agents/{agent_1_id}/policy/{policy_id}")
    client.post(f"/api/v1/agents/{agent_2_id}/policy/{policy_id}")

    # Verify both see same controls initially
    resp_1 = client.get(f"/api/v1/agents/{agent_1_id}/controls")
    resp_2 = client.get(f"/api/v1/agents/{agent_2_id}/controls")
    assert len(resp_1.json()["controls"]) == 2
    assert len(resp_2.json()["controls"]) == 2

    # When: Add new control to policy
    control_3_id = _create_control(client, "control-3", {"id": 3})
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_3_id}")

    # Then: Both agents see the new control
    resp_1 = client.get(f"/api/v1/agents/{agent_1_id}/controls")
    resp_2 = client.get(f"/api/v1/agents/{agent_2_id}/controls")

    controls_1 = resp_1.json()["controls"]
    controls_2 = resp_2.json()["controls"]

    assert len(controls_1) == 3
    assert len(controls_2) == 3
    expected = {control_1_id, control_2_id, control_3_id}
    assert {r["id"] for r in controls_1} == expected
    assert {r["id"] for r in controls_2} == expected


def test_control_shared_between_policies(client: TestClient) -> None:
    """Same control can be added to multiple policies."""
    # Given: One control and two policies
    control_id = _create_control(client, "shared-control", {"shared": True})
    policy_a_id = _create_policy(client, "policy-a")
    policy_b_id = _create_policy(client, "policy-b")

    # When: Add the same control to both policies
    resp = client.post(f"/api/v1/policies/{policy_a_id}/controls/{control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_b_id}/controls/{control_id}")
    assert resp.status_code == 200

    # Then: Both policies show the control
    resp_a = client.get(f"/api/v1/policies/{policy_a_id}/controls")
    resp_b = client.get(f"/api/v1/policies/{policy_b_id}/controls")

    assert control_id in resp_a.json()["control_ids"]
    assert control_id in resp_b.json()["control_ids"]

    # And: Agents with either policy see the control
    agent_a_id, _ = _create_agent(client, "agent-alpha-01")
    agent_b_id, _ = _create_agent(client, "agent-beta-02")

    client.post(f"/api/v1/agents/{agent_a_id}/policy/{policy_a_id}")
    client.post(f"/api/v1/agents/{agent_b_id}/policy/{policy_b_id}")

    resp_a = client.get(f"/api/v1/agents/{agent_a_id}/controls")
    resp_b = client.get(f"/api/v1/agents/{agent_b_id}/controls")

    assert control_id in {c["id"] for c in resp_a.json()["controls"]}
    assert control_id in {c["id"] for c in resp_b.json()["controls"]}


def test_agent_controls_union_across_multiple_policies_with_dedupe(client: TestClient) -> None:
    """Agent controls should be additive across policies and deduplicated by control id."""
    agent_name, _ = _create_agent(client)
    policy_a_id = _create_policy(client, "policy-a")
    policy_b_id = _create_policy(client, "policy-b")

    shared_control_id = _create_control(client)
    policy_a_only_control_id = _create_control(client)
    policy_b_only_control_id = _create_control(client)

    # Policy A: shared + A-only
    resp = client.post(f"/api/v1/policies/{policy_a_id}/controls/{shared_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_a_id}/controls/{policy_a_only_control_id}")
    assert resp.status_code == 200

    # Policy B: shared + B-only
    resp = client.post(f"/api/v1/policies/{policy_b_id}/controls/{shared_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_b_id}/controls/{policy_b_only_control_id}")
    assert resp.status_code == 200

    # Associate both policies with the same agent (plural additive endpoint).
    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_a_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_b_id}")
    assert resp.status_code == 200

    # Agent should have both policy associations.
    policies_resp = client.get(f"/api/v1/agents/{agent_name}/policies")
    assert policies_resp.status_code == 200
    assert policies_resp.json()["policy_ids"] == [policy_a_id, policy_b_id]

    # Active controls should be union(policy A, policy B) with shared deduped.
    controls_resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert controls_resp.status_code == 200
    controls = controls_resp.json()["controls"]
    received_control_ids = {control["id"] for control in controls}
    assert received_control_ids == {
        shared_control_id,
        policy_a_only_control_id,
        policy_b_only_control_id,
    }
    assert len(controls) == 3

    # list_agents count should match the deduplicated union.
    agents_resp = client.get("/api/v1/agents", params={"name": agent_name})
    assert agents_resp.status_code == 200
    matching_agents = [
        agent for agent in agents_resp.json()["agents"] if agent["agent_name"] == agent_name
    ]
    assert len(matching_agents) == 1
    assert matching_agents[0]["active_controls_count"] == 3


def test_remove_one_policy_keeps_controls_from_remaining_policies(client: TestClient) -> None:
    """Removing one policy should preserve controls inherited from other policies."""
    agent_name, _ = _create_agent(client)
    policy_a_id = _create_policy(client, "policy-a")
    policy_b_id = _create_policy(client, "policy-b")

    shared_control_id = _create_control(client)
    policy_a_only_control_id = _create_control(client)
    policy_b_only_control_id = _create_control(client)

    # Policy A: shared + A-only
    resp = client.post(f"/api/v1/policies/{policy_a_id}/controls/{shared_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_a_id}/controls/{policy_a_only_control_id}")
    assert resp.status_code == 200

    # Policy B: shared + B-only
    resp = client.post(f"/api/v1/policies/{policy_b_id}/controls/{shared_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_b_id}/controls/{policy_b_only_control_id}")
    assert resp.status_code == 200

    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_a_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_b_id}")
    assert resp.status_code == 200

    # Remove only policy A.
    resp = client.delete(f"/api/v1/agents/{agent_name}/policies/{policy_a_id}")
    assert resp.status_code == 200

    policies_resp = client.get(f"/api/v1/agents/{agent_name}/policies")
    assert policies_resp.status_code == 200
    assert policies_resp.json()["policy_ids"] == [policy_b_id]

    controls_resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert controls_resp.status_code == 200
    received_control_ids = {control["id"] for control in controls_resp.json()["controls"]}
    assert received_control_ids == {shared_control_id, policy_b_only_control_id}


def test_remove_all_policies_preserves_direct_controls(client: TestClient) -> None:
    """Removing all policy links should keep direct agent-control associations active."""
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)
    policy_control_id = _create_control(client)
    direct_control_id = _create_control(client)

    resp = client.post(f"/api/v1/policies/{policy_id}/controls/{policy_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{direct_control_id}")
    assert resp.status_code == 200

    resp = client.delete(f"/api/v1/agents/{agent_name}/policies")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    policies_resp = client.get(f"/api/v1/agents/{agent_name}/policies")
    assert policies_resp.status_code == 200
    assert policies_resp.json()["policy_ids"] == []

    controls_resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert controls_resp.status_code == 200
    assert {control["id"] for control in controls_resp.json()["controls"]} == {direct_control_id}


def test_add_agent_policy_is_idempotent(client: TestClient) -> None:
    """Adding the same policy association twice should not duplicate links."""
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)

    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_id}")
    assert resp.status_code == 200

    policies_resp = client.get(f"/api/v1/agents/{agent_name}/policies")
    assert policies_resp.status_code == 200
    assert policies_resp.json()["policy_ids"] == [policy_id]


def test_add_agent_control_is_idempotent(client: TestClient) -> None:
    """Adding the same direct control twice should not duplicate active controls."""
    agent_name, _ = _create_agent(client)
    control_id = _create_control(client)

    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200

    controls_resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert controls_resp.status_code == 200
    controls = controls_resp.json()["controls"]
    assert {control["id"] for control in controls} == {control_id}
    assert len(controls) == 1


def test_agent_policy_endpoints_return_404_for_missing_resources(client: TestClient) -> None:
    """Plural policy endpoints should return consistent 404s for missing agent/policy."""
    existing_agent_name, _ = _create_agent(client)
    existing_policy_id = _create_policy(client)

    missing_agent_name = "missing-agent-1234"
    missing_policy_id = 999999

    # Missing agent on add/list/remove-one/remove-all.
    resp = client.post(f"/api/v1/agents/{missing_agent_name}/policies/{existing_policy_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"

    resp = client.get(f"/api/v1/agents/{missing_agent_name}/policies")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"

    resp = client.delete(f"/api/v1/agents/{missing_agent_name}/policies/{existing_policy_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"

    resp = client.delete(f"/api/v1/agents/{missing_agent_name}/policies")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"

    # Missing policy on add/remove-one.
    resp = client.post(f"/api/v1/agents/{existing_agent_name}/policies/{missing_policy_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "POLICY_NOT_FOUND"

    resp = client.delete(f"/api/v1/agents/{existing_agent_name}/policies/{missing_policy_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "POLICY_NOT_FOUND"


def test_agent_control_endpoints_return_404_for_missing_resources(client: TestClient) -> None:
    """Direct control association endpoints should return 404s for missing agent/control."""
    existing_agent_name, _ = _create_agent(client)
    existing_control_id = _create_control(client)

    missing_agent_name = "missing-agent-1234"
    missing_control_id = 999999

    # Missing agent on add/remove.
    resp = client.post(f"/api/v1/agents/{missing_agent_name}/controls/{existing_control_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"

    resp = client.delete(f"/api/v1/agents/{missing_agent_name}/controls/{existing_control_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"

    # Missing control on add/remove.
    resp = client.post(f"/api/v1/agents/{existing_agent_name}/controls/{missing_control_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"

    resp = client.delete(f"/api/v1/agents/{existing_agent_name}/controls/{missing_control_id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_agent_gets_controls_from_direct_associations(client: TestClient) -> None:
    """Agent should see controls directly associated with it."""
    agent_name, _ = _create_agent(client)
    control_1_id = _create_control(client)
    control_2_id = _create_control(client)

    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_1_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_2_id}")
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert resp.status_code == 200
    controls = resp.json()["controls"]
    assert {control["id"] for control in controls} == {control_1_id, control_2_id}


def test_agent_controls_are_union_of_policy_and_direct_with_dedupe(client: TestClient) -> None:
    """Agent control list should union policy + direct controls and de-duplicate by control id."""
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)

    shared_control_id = _create_control(client)
    policy_only_control_id = _create_control(client)
    direct_only_control_id = _create_control(client)

    # Associate shared + policy-only controls via policy.
    resp = client.post(f"/api/v1/policies/{policy_id}/controls/{shared_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/policies/{policy_id}/controls/{policy_only_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_id}")
    assert resp.status_code == 200

    # Associate shared + direct-only controls directly with agent.
    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{shared_control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{direct_only_control_id}")
    assert resp.status_code == 200

    # Shared control should appear only once in active controls.
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert resp.status_code == 200
    controls = resp.json()["controls"]
    received_control_ids = {control["id"] for control in controls}
    assert received_control_ids == {shared_control_id, policy_only_control_id, direct_only_control_id}
    assert len(controls) == 3

    # list_agents active_controls_count should reflect deduplicated union as well.
    agents_resp = client.get("/api/v1/agents", params={"name": agent_name})
    assert agents_resp.status_code == 200
    matching_agents = [
        agent for agent in agents_resp.json()["agents"] if agent["agent_name"] == agent_name
    ]
    assert len(matching_agents) == 1
    assert matching_agents[0]["active_controls_count"] == 3


def test_remove_direct_control_keeps_policy_inherited_control_active(client: TestClient) -> None:
    """Removing a direct association should keep control active when policy still provides it."""
    agent_name, _ = _create_agent(client)
    policy_id = _create_policy(client)
    control_id = _create_control(client)

    resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/policies/{policy_id}")
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200

    resp = client.delete(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["removed_direct_association"] is True
    assert body["control_still_active"] is True

    # Idempotent behavior when no direct link remains but policy inheritance still exists.
    resp = client.delete(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["removed_direct_association"] is False
    assert body["control_still_active"] is True

    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert resp.status_code == 200
    assert control_id in {control["id"] for control in resp.json()["controls"]}


def test_remove_direct_control_deactivates_when_not_inherited(client: TestClient) -> None:
    """Removing a direct-only control should make it inactive for the agent."""
    agent_name, _ = _create_agent(client)
    control_id = _create_control(client)

    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200

    resp = client.delete(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["removed_direct_association"] is True
    assert body["control_still_active"] is False

    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert resp.status_code == 200
    assert control_id not in {control["id"] for control in resp.json()["controls"]}
