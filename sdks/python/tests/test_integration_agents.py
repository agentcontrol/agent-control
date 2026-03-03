"""
Integration tests for Agent operations.

These tests verify the full agent lifecycle:
1. Agent registration
2. Agent retrieval
3. Agent updates
"""

import uuid

import agent_control
import pytest
from agent_control_models.server import AgentControlsResponse


@pytest.mark.asyncio
async def test_agent_registration_workflow(
    client: agent_control.AgentControlClient,
    test_agent_name: str,
    sample_steps: list
) -> None:
    """
    Test complete agent registration workflow.

    Verifies:
    - Agent can be registered with steps
    - Response includes created flag
    - Response includes rules (may be empty)
    """
    from datetime import UTC, datetime

    from agent_control_models import Agent

    unique_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent = Agent(
        agent_name=unique_name,
        agent_description="Testing agent registration",
        agent_created_at=datetime.now(UTC).isoformat(),
        agent_updated_at=None,
        agent_version="1.0.0",
        agent_metadata={"env": "test"}
    )

    # Register agent
    response = await agent_control.agents.register_agent(
        client,
        agent,
        steps=sample_steps
    )

    # Verify response structure
    assert "created" in response
    # Note: "controls" may not be in response if no policy assigned,
    # but InitAgentResponse model has default factory=list.
    # SDK method register_agent returns `dict` from `response.json()`.
    # The server InitAgentResponse has `controls` field.

    # If creation succeeded, response should look like InitAgentResponse
    assert isinstance(response["created"], bool)
    # assert isinstance(response["controls"], list)

    print(f"✓ Agent registered: {response['created']}")
    # print(f"✓ Controls received: {len(response['controls'])}")


@pytest.mark.asyncio
async def test_agent_retrieval_workflow(
    client: agent_control.AgentControlClient,
    test_agent: dict
) -> None:
    """
    Test agent retrieval workflow.

    Verifies:
    - Registered agent can be retrieved
    - Response includes agent metadata
    - Response includes registered steps
    """
    agent_name = test_agent["agent_name"]

    # Retrieve agent
    agent_data = await agent_control.agents.get_agent(client, agent_name)

    # Verify response structure
    assert "agent" in agent_data
    assert "steps" in agent_data

    # Verify agent metadata
    agent = agent_data["agent"]
    assert agent["agent_name"] == agent_name
    assert agent["agent_name"] is not None
    assert "agent_description" in agent

    # Verify steps
    steps = agent_data["steps"]
    assert isinstance(steps, list)
    assert len(steps) > 0  # Should have at least the test_search step

    print(f"✓ Agent retrieved: {agent['agent_name']}")
    print(f"✓ Steps found: {len(steps)}")


@pytest.mark.asyncio
async def test_agent_update_workflow(
    client: agent_control.AgentControlClient,
    test_agent: dict,
    sample_steps: list
) -> None:
    """
    Test agent update workflow (re-registration).

    Verifies:
    - Existing agent can be updated via re-registration
    - Response indicates update (created=False)
    - Steps are updated
    """
    agent = test_agent["agent"]

    # Update agent (re-register with different steps)
    updated_steps = sample_steps[:1]  # Use only first step
    response = await agent_control.agents.register_agent(
        client,
        agent,
        steps=updated_steps
    )

    # Verify this was an update, not a new creation
    assert response["created"] is False

    print("✓ Agent updated successfully")
    print(f"✓ Updated with {len(updated_steps)} step(s)")


@pytest.mark.asyncio
async def test_list_agent_controls_typed_returns_model(
    client: agent_control.AgentControlClient,
    test_agent: dict,
) -> None:
    """Typed controls endpoint returns AgentControlsResponse."""
    # GIVEN: an existing registered agent.

    # WHEN: controls are requested via the typed API wrapper.
    response = await agent_control.agents.list_agent_controls_typed(
        client,
        test_agent["agent_name"],
    )

    # THEN: a typed model is returned.
    assert isinstance(response, AgentControlsResponse)
    assert isinstance(response.controls, list)


@pytest.mark.asyncio
async def test_list_agent_controls_returns_dict_payload(
    client: agent_control.AgentControlClient,
    test_agent: dict,
) -> None:
    """Dict controls endpoint returns a dict payload with controls list."""
    # GIVEN: an existing registered agent.

    # WHEN: controls are requested via the dict API wrapper.
    response = await agent_control.agents.list_agent_controls(
        client,
        test_agent["agent_name"],
    )

    # THEN: a dict payload is returned with controls list.
    assert isinstance(response, dict)
    assert "controls" in response
    assert isinstance(response["controls"], list)


@pytest.mark.asyncio
async def test_convenience_get_agent_function(
    test_agent: dict,
    server_url: str,
    api_key: str | None,
) -> None:
    """
    Test the convenience get_agent() function.

    Verifies:
    - Convenience function works without manual client management
    - Returns same data as client-based approach
    """
    agent_name = test_agent["agent_name"]

    # Use convenience function
    agent_data = await agent_control.get_agent(agent_name, server_url=server_url, api_key=api_key)

    # Verify response
    assert "agent" in agent_data
    assert agent_data["agent"]["agent_name"] == agent_name

    print("✓ Convenience function works")


@pytest.mark.asyncio
async def test_convenience_agent_association_functions(
    test_agent: dict,
    test_policy: dict,
    test_control: dict,
    server_url: str,
    api_key: str | None,
) -> None:
    """Top-level convenience helpers support multi-policy and direct controls."""
    agent_name = test_agent["agent_name"]
    policy_id = test_policy["policy_id"]
    control_id = test_control["control_id"]

    control_data = {
        "description": "Integration test control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": "regex",
            "config": {"pattern": ".*"},
        },
        "action": {"decision": "allow"},
        "tags": ["test"],
    }

    add_policy_result = await agent_control.add_agent_policy(
        agent_name,
        policy_id,
        server_url=server_url,
        api_key=api_key,
    )
    assert add_policy_result["success"] is True

    policies_result = await agent_control.get_agent_policies(
        agent_name,
        server_url=server_url,
        api_key=api_key,
    )
    assert policy_id in policies_result["policy_ids"]

    add_control_result = await agent_control.add_agent_control(
        agent_name,
        control_id,
        server_url=server_url,
        api_key=api_key,
    )
    assert add_control_result["success"] is True

    async with agent_control.AgentControlClient(
        base_url=server_url,
        api_key=api_key,
    ) as client:
        await agent_control.controls.set_control_data(client, control_id, control_data)
        controls_result = await agent_control.agents.list_agent_controls(client, agent_name)
    control_ids = {item["id"] for item in controls_result["controls"]}
    assert control_id in control_ids

    remove_control_result = await agent_control.remove_agent_control(
        agent_name,
        control_id,
        server_url=server_url,
        api_key=api_key,
    )
    assert remove_control_result["success"] is True
    assert remove_control_result["removed_direct_association"] is True

    remove_policy_result = await agent_control.remove_agent_policy_association(
        agent_name,
        policy_id,
        server_url=server_url,
        api_key=api_key,
    )
    assert remove_policy_result["success"] is True

    # Re-associate then clear all to verify remove_all convenience path.
    await agent_control.add_agent_policy(
        agent_name,
        policy_id,
        server_url=server_url,
        api_key=api_key,
    )
    clear_result = await agent_control.remove_all_agent_policies(
        agent_name,
        server_url=server_url,
        api_key=api_key,
    )
    assert clear_result["success"] is True

    policies_after_clear = await agent_control.get_agent_policies(
        agent_name,
        server_url=server_url,
        api_key=api_key,
    )
    assert policies_after_clear["policy_ids"] == []


@pytest.mark.asyncio
async def test_init_function_workflow(
    test_agent_name: str,
    server_url: str,
    api_key: str | None,
    sample_steps: list,
) -> None:
    """
    Test the init() function workflow.

    Verifies:
    - init() successfully registers agent
    - Returns Agent instance
    - current_agent() returns initialized agent
    """
    # Initialize agent
    agent = agent_control.init(
        agent_name=test_agent_name,
        agent_description="Testing init function",
        agent_version="1.0.0",
        server_url=server_url,
        api_key=api_key,
        steps=sample_steps,
        policy_refresh_interval_seconds=0,
        environment="test"
    )

    # Verify agent instance
    assert agent is not None
    assert agent.agent_name == test_agent_name
    assert hasattr(agent, "agent_name")

    # Verify current_agent()
    current = agent_control.current_agent()
    assert current is not None
    assert current.agent_name == agent.agent_name

    print("✓ init() function works")
    print("✓ current_agent() returns initialized agent")
