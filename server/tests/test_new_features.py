"""Tests for new features: evaluators endpoint, policy validation, PATCH agents."""

import uuid

from fastapi.testclient import TestClient


def make_agent_payload(
    agent_name: str | None = None,
    name: str | None = None,
    steps: list | None = None,
    evaluators: list | None = None,
):
    """Helper to create agent payload."""
    if agent_name is not None:
        name = agent_name
    elif name is None:
        name = f"agent-{uuid.uuid4().hex[:12]}"
    canonical_name = name.lower().replace(" ", "-")
    if len(canonical_name) < 10:
        canonical_name = f"{canonical_name}-agent".replace("--", "-")
    return {
        "agent": {
            "agent_name": canonical_name,
            "agent_name": canonical_name,
            "agent_description": "desc",
            "agent_version": "1.0",
        },
        "steps": steps or [],
        "evaluators": evaluators or [],
    }


# =============================================================================
# GET /evaluators endpoint
# =============================================================================


def test_get_evaluators(client: TestClient) -> None:
    """Given built-in evaluators are registered, when listing evaluators, then returns all with schemas."""
    # Given: built-in evaluators are registered
    # When: listing evaluators
    resp = client.get("/api/v1/evaluators")

    # Then: response includes built-in evaluators with schemas
    assert resp.status_code == 200
    evaluators = resp.json()
    assert isinstance(evaluators, dict)
    assert "regex" in evaluators
    assert "list" in evaluators

    regex = evaluators["regex"]
    assert regex["name"] == "regex"
    assert "version" in regex
    assert "description" in regex
    assert "config_schema" in regex
    assert isinstance(regex["config_schema"], dict)


def test_get_evaluators_schema_has_properties(client: TestClient) -> None:
    """Given the regex evaluator is registered, when listing evaluators, then schema has pattern property."""
    # Given: the regex evaluator is registered
    # When: listing evaluators
    resp = client.get("/api/v1/evaluators")

    # Then: regex schema includes expected properties
    assert resp.status_code == 200
    evaluators = resp.json()
    regex_schema = evaluators["regex"]["config_schema"]
    assert "properties" in regex_schema
    assert "pattern" in regex_schema["properties"]


# =============================================================================
# PATCH /agents endpoint
# =============================================================================


def test_patch_agent_remove_step(client: TestClient) -> None:
    """Given an agent with multiple steps, when removing one step, then only that step is removed."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload = make_agent_payload(
        agent_name=agent_name,
        name=name,
        steps=[
            {"type": "tool", "name": "tool1", "input_schema": {}, "output_schema": {}},
            {"type": "tool", "name": "tool2", "input_schema": {}, "output_schema": {}},
        ],
    )
    client.post("/api/v1/agents/initAgent", json=payload)

    # When:
    patch_resp = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={"remove_steps": [{"type": "tool", "name": "tool1"}]},
    )

    # Then:
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["steps_removed"] == [{"type": "tool", "name": "tool1"}]
    assert data["evaluators_removed"] == []

    get_resp = client.get(f"/api/v1/agents/{agent_name}")
    steps = [s["name"] for s in get_resp.json()["steps"]]
    assert "tool1" not in steps
    assert "tool2" in steps


def test_patch_agent_remove_evaluator(client: TestClient) -> None:
    """Given an agent with multiple evaluators, when removing one, then only that evaluator is removed."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {"name": "eval1", "config_schema": {}},
            {"name": "eval2", "config_schema": {}},
        ],
    )
    client.post("/api/v1/agents/initAgent", json=payload)

    # When:
    patch_resp = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={"remove_evaluators": ["eval1"]},
    )

    # Then:
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["evaluators_removed"] == ["eval1"]

    get_resp = client.get(f"/api/v1/agents/{agent_name}/evaluators")
    evals = [e["name"] for e in get_resp.json()["evaluators"]]
    assert "eval1" not in evals
    assert "eval2" in evals


def test_patch_agent_remove_nonexistent_is_idempotent(client: TestClient) -> None:
    """Given an agent, when removing nonexistent items, then succeeds with empty removed lists."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload = make_agent_payload(agent_name=agent_name, name=name)
    client.post("/api/v1/agents/initAgent", json=payload)

    # When:
    patch_resp = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={
            "remove_steps": [{"type": "tool", "name": "nonexistent"}],
            "remove_evaluators": ["also_nonexistent"],
        },
    )

    # Then:
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["steps_removed"] == []
    assert data["evaluators_removed"] == []


def test_patch_agent_not_found(client: TestClient) -> None:
    """Given a nonexistent agent UUID, when patching, then returns 404."""
    # Given:
    fake_id = str(uuid.uuid4())

    # When:
    patch_resp = client.patch(
        f"/api/v1/agents/{fake_id}",
        json={"remove_steps": [{"type": "tool", "name": "tool1"}]},
    )

    # Then:
    assert patch_resp.status_code == 404


def test_patch_agent_remove_both(client: TestClient) -> None:
    """Given an agent with steps and evaluators, when removing both, then both are removed."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload = make_agent_payload(
        agent_name=agent_name,
        name=name,
        steps=[{"type": "tool", "name": "my_tool", "input_schema": {}, "output_schema": {}}],
        evaluators=[{"name": "my_eval", "config_schema": {}}],
    )
    client.post("/api/v1/agents/initAgent", json=payload)

    # When:
    patch_resp = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={
            "remove_steps": [{"type": "tool", "name": "my_tool"}],
            "remove_evaluators": ["my_eval"],
        },
    )

    # Then:
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["steps_removed"] == [{"type": "tool", "name": "my_tool"}]
    assert data["evaluators_removed"] == ["my_eval"]


def test_patch_agent_empty_request_is_noop(client: TestClient) -> None:
    """Given an agent, when patching with empty lists, then nothing changes and succeeds."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload = make_agent_payload(
        agent_name=agent_name,
        name=name,
        steps=[{"type": "tool", "name": "keep_me", "input_schema": {}, "output_schema": {}}],
        evaluators=[{"name": "keep_me_too", "config_schema": {}}],
    )
    client.post("/api/v1/agents/initAgent", json=payload)

    # When:
    patch_resp = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={"remove_steps": [], "remove_evaluators": []},
    )

    # Then:
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["steps_removed"] == []
    assert data["evaluators_removed"] == []

    # Verify nothing was removed
    get_resp = client.get(f"/api/v1/agents/{agent_name}")
    steps = [s["name"] for s in get_resp.json()["steps"]]
    assert "keep_me" in steps

    get_evals = client.get(f"/api/v1/agents/{agent_name}/evaluators")
    evals = [e["name"] for e in get_evals.json()["evaluators"]]
    assert "keep_me_too" in evals


# =============================================================================
# Policy assignment validation
# =============================================================================


def _create_policy_with_control(
    client: TestClient, policy_name: str, control_name: str, control_data: dict
) -> tuple[int, int]:
    """Helper to create a policy with a control.

    Returns (policy_id, control_id).
    """
    # Create policy
    pol_resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert pol_resp.status_code == 200
    policy_id = pol_resp.json()["policy_id"]

    # Create control
    ctl_resp = client.put("/api/v1/controls", json={"name": control_name})
    assert ctl_resp.status_code == 200
    control_id = ctl_resp.json()["control_id"]

    # Set control data
    data_resp = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": control_data},
    )
    assert data_resp.status_code == 200

    # Add control to policy
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")

    return policy_id, control_id


def test_policy_assignment_with_builtin_evaluator(client: TestClient) -> None:
    """Given an agent and a policy with built-in evaluator control, when assigning policy, then succeeds."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload = make_agent_payload(agent_name=agent_name, name=name)
    client.post("/api/v1/agents/initAgent", json=payload)

    policy_id, _ = _create_policy_with_control(
        client,
        f"policy-{uuid.uuid4().hex[:8]}",
        f"control-{uuid.uuid4().hex[:8]}",
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {"name": "regex", "config": {"pattern": "test.*"}},
            "action": {"decision": "deny"},
        },
    )

    # When:
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # Then:
    assert resp.status_code == 200


def test_policy_assignment_with_registered_agent_evaluator(client: TestClient) -> None:
    """Given an agent with custom evaluator and matching policy, when assigning policy, then succeeds."""
    # Given:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    payload = make_agent_payload(
        agent_name=agent_name,
        name=agent_name,
        evaluators=[{"name": "custom-eval", "config_schema": {"type": "object"}}],
    )
    client.post("/api/v1/agents/initAgent", json=payload)

    policy_id, _ = _create_policy_with_control(
        client,
        f"policy-{uuid.uuid4().hex[:8]}",
        f"control-{uuid.uuid4().hex[:8]}",
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {"name": f"{agent_name}:custom-eval", "config": {}},
            "action": {"decision": "deny"},
        },
    )

    # When:
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # Then:
    assert resp.status_code == 200


def test_control_creation_with_unregistered_evaluator_fails(client: TestClient) -> None:
    """Given an agent without evaluator, when setting control to use that evaluator, then fails."""
    # Given:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    payload = make_agent_payload(agent_name=agent_name, name=agent_name)
    client.post("/api/v1/agents/initAgent", json=payload)

    ctl_resp = client.put("/api/v1/controls", json={"name": f"control-{uuid.uuid4().hex[:8]}"})
    control_id = ctl_resp.json()["control_id"]

    # When:
    data_resp = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={
            "data": {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "selector": {"path": "input"},
                "evaluator": {"name": f"{agent_name}:nonexistent-eval", "config": {}},
                "action": {"decision": "deny"},
            }
        },
    )

    # Then: (RFC 7807 format)
    assert data_resp.status_code == 422
    response_data = data_resp.json()
    # Check detail message or errors array
    assert "not registered" in response_data.get("detail", "")


def test_policy_assignment_cross_agent_evaluator_fails(client: TestClient) -> None:
    """Given policy with Agent A's evaluator, when assigning to Agent B, then fails."""
    # Given: Agent A has evaluator, Agent B does not
    agent_a_id = f"agent-a-{uuid.uuid4().hex[:12]}"
    agent_a_name = agent_a_id
    payload_a = make_agent_payload(
        agent_name=agent_a_id,
        name=agent_a_name,
        evaluators=[{"name": "shared-eval", "config_schema": {"type": "object"}}],
    )
    client.post("/api/v1/agents/initAgent", json=payload_a)

    agent_b_id = f"agent-b-{uuid.uuid4().hex[:12]}"
    agent_b_name = agent_b_id
    payload_b = make_agent_payload(agent_name=agent_b_id, name=agent_b_name)
    client.post("/api/v1/agents/initAgent", json=payload_b)

    policy_id, _ = _create_policy_with_control(
        client,
        f"policy-{uuid.uuid4().hex[:8]}",
        f"control-{uuid.uuid4().hex[:8]}",
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {"name": f"{agent_a_name}:shared-eval", "config": {}},
            "action": {"decision": "deny"},
        },
    )

    # When: Assign to Agent A (should succeed)
    resp_a = client.post(f"/api/v1/agents/{agent_a_id}/policy/{policy_id}")

    # Then:
    assert resp_a.status_code == 200

    # When: Assign same policy to Agent B (should fail)
    resp_b = client.post(f"/api/v1/agents/{agent_b_id}/policy/{policy_id}")

    # Then: (RFC 7807 format)
    assert resp_b.status_code == 400
    response_data = resp_b.json()
    assert "incompatible" in response_data.get("detail", "").lower()
    errors = response_data.get("errors", [])
    assert any(agent_a_name in e.get("message", "") for e in errors)


# =============================================================================
# Nested schema compatibility tests
# =============================================================================


def test_schema_compat_nested_additional_properties_compatible(client: TestClient) -> None:
    """Given a nested schema, when adding optional property in nested object, then compatible."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload1 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "nested-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "options": {
                            "type": "object",
                            "properties": {"level": {"type": "number"}},
                        }
                    },
                },
            }
        ],
    )
    client.post("/api/v1/agents/initAgent", json=payload1)

    # When: add optional property in nested object
    payload2 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "nested-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "options": {
                            "type": "object",
                            "properties": {
                                "level": {"type": "number"},
                                "extra": {"type": "string"},
                            },
                        }
                    },
                },
            }
        ],
    )
    resp2 = client.post("/api/v1/agents/initAgent", json=payload2)

    # Then:
    assert resp2.status_code == 200


def test_schema_compat_nested_type_change_incompatible(client: TestClient) -> None:
    """Given a nested schema, when changing nested property type, then rejected as incompatible."""
    # Given:
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload1 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "nested-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "settings": {
                            "type": "object",
                            "properties": {"count": {"type": "integer"}},
                        }
                    },
                },
            }
        ],
    )
    client.post("/api/v1/agents/initAgent", json=payload1)

    # When: change nested type from integer to string
    payload2 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "nested-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "settings": {
                            "type": "object",
                            "properties": {"count": {"type": "string"}},
                        }
                    },
                },
            }
        ],
    )
    resp2 = client.post("/api/v1/agents/initAgent", json=payload2)

    # Then:
    assert resp2.status_code == 409
    assert "not backward compatible" in resp2.json()["detail"]


# =============================================================================
# Evaluator removal protection
# =============================================================================


def test_patch_agent_remove_evaluator_blocked_by_control(client: TestClient) -> None:
    """Given an agent with evaluator used by a control, when removing evaluator, then rejected.

    Given: An agent with evaluator "my-eval" and a control using that evaluator
    When: Trying to remove "my-eval" via PATCH
    Then: Returns 409 with error message about referencing control
    """
    # Given: Agent with custom evaluator
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    payload = make_agent_payload(
        agent_name=agent_name,
        name=agent_name,
        evaluators=[{"name": "my-eval", "config_schema": {"type": "object"}}],
    )
    client.post("/api/v1/agents/initAgent", json=payload)

    # And: A control set up to use that evaluator
    policy_id, _ = _create_policy_with_control(
        client,
        f"policy-{uuid.uuid4().hex[:8]}",
        f"control-{uuid.uuid4().hex[:8]}",
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {"name": f"{agent_name}:my-eval", "config": {}},
            "action": {"decision": "deny"},
        },
    )

    # And: Policy assigned to agent
    assign_resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    assert assign_resp.status_code == 200

    # When: Trying to remove the evaluator
    patch_resp = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={"remove_evaluators": ["my-eval"]},
    )

    # Then: Should be rejected with 409 (RFC 7807 format)
    assert patch_resp.status_code == 409
    response_data = patch_resp.json()
    detail = response_data.get("detail", "")
    errors = response_data.get("errors", [])
    assert "Cannot remove evaluators" in detail
    # Check errors array contains reference to the evaluator
    assert any("my-eval" in e.get("message", "") for e in errors)


def test_patch_agent_remove_evaluator_allowed_without_policy(client: TestClient) -> None:
    """Given an agent with evaluator but no policy, when removing evaluator, then succeeds.

    Given: An agent with evaluator "my-eval" but no policy assigned
    When: Trying to remove "my-eval" via PATCH
    Then: Succeeds since no controls can reference it
    """
    # Given: Agent with custom evaluator but no policy
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    payload = make_agent_payload(
        agent_name=agent_name,
        name=agent_name,
        evaluators=[{"name": "my-eval", "config_schema": {"type": "object"}}],
    )
    client.post("/api/v1/agents/initAgent", json=payload)

    # When: Removing the evaluator (no policy = no controls can reference it)
    patch_resp = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={"remove_evaluators": ["my-eval"]},
    )

    # Then: Should succeed
    assert patch_resp.status_code == 200
    assert patch_resp.json()["evaluators_removed"] == ["my-eval"]
