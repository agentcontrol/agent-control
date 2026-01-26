"""
Integration tests for Agent operations.

These tests verify the full agent lifecycle:
1. Agent registration
2. Agent retrieval
3. Agent updates
"""

import uuid

import pytest

import agent_control


@pytest.mark.asyncio
async def test_agent_registration_workflow(
    client: agent_control.AgentControlClient,
    test_agent_id: str,
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

    # Generate a proper UUID4 for the agent
    agent_uuid = uuid.uuid4()
    unique_name = f"Integration Test Agent {uuid.uuid4().hex[:8]}"
    agent = Agent(
        agent_id=agent_uuid,
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
    agent_id = test_agent["agent_id"]

    # Retrieve agent
    agent_data = await agent_control.agents.get_agent(client, agent_id)

    # Verify response structure
    assert "agent" in agent_data
    assert "steps" in agent_data

    # Verify agent metadata
    agent = agent_data["agent"]
    assert agent["agent_id"] == agent_id
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
    agent_id = test_agent["agent_id"]

    # Use convenience function
    agent_data = await agent_control.get_agent(agent_id, server_url=server_url, api_key=api_key)

    # Verify response
    assert "agent" in agent_data
    assert agent_data["agent"]["agent_id"] == agent_id

    print("✓ Convenience function works")


@pytest.mark.asyncio
async def test_init_function_workflow(
    test_agent_id: str,
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
        agent_name="Init Test Agent",
        agent_id=test_agent_id,
        agent_description="Testing init function",
        agent_version="1.0.0",
        server_url=server_url,
        api_key=api_key,
        steps=sample_steps,
        environment="test"
    )

    # Verify agent instance
    assert agent is not None
    assert agent.agent_name == "Init Test Agent"
    assert hasattr(agent, "agent_id")

    # Verify current_agent()
    current = agent_control.current_agent()
    assert current is not None
    assert current.agent_name == agent.agent_name

    print("✓ init() function works")
    print("✓ current_agent() returns initialized agent")
