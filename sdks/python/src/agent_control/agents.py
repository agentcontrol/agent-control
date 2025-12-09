"""Agent management operations for Agent Control SDK."""

from typing import Any, cast
from uuid import UUID

from .client import AgentControlClient

# Import models if available
try:
    from agent_control_models import Agent
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    Agent = Any  # type: ignore


async def register_agent(
    client: AgentControlClient,
    agent: Agent,
    tools: list[dict[str, Any]] | None = None,
    policies: list[str] | None = None
) -> dict[str, Any]:
    """
    Register an agent with the server via /initAgent endpoint.

    Args:
        client: AgentControlClient instance
        agent: Agent instance to register
        tools: Optional list of tools with their schemas
        policies: Optional list of policy names required by the agent

    Returns:
        InitAgentResponse with created flag and controls
    """
    if tools is None:
        tools = []
    if policies is None:
        policies = []

    if MODELS_AVAILABLE:
        agent_dict = agent.to_dict()
        # Ensure UUID is converted to string for JSON serialization
        if isinstance(agent_dict.get('agent_id'), UUID):
            agent_dict['agent_id'] = str(agent_dict['agent_id'])
        payload = {
            "agent": agent_dict,
            "tools": tools,
            "policies": policies
        }
    else:
        payload = {
            "agent": {
                "agent_id": str(agent.agent_id),
                "agent_name": agent.agent_name,
                "agent_description": getattr(agent, 'agent_description', None),
                "agent_version": getattr(agent, 'agent_version', None),
                "agent_metadata": getattr(agent, 'agent_metadata', None),
            },
            "tools": tools,
            "policies": policies
        }

    response = await client.http_client.post("/api/v1/agents/initAgent", json=payload)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def get_agent(
    client: AgentControlClient,
    agent_id: str
) -> dict[str, Any]:
    """
    Get agent details by ID from the server.

    Args:
        client: AgentControlClient instance
        agent_id: UUID or string identifier of the agent

    Returns:
        Dictionary containing:
            - agent: Agent metadata
            - tools: List of tools registered with the agent

    Raises:
        httpx.HTTPError: If request fails or agent not found (404)

    Example:
        async with AgentControlClient() as client:
            agent_data = await get_agent(client, "550e8400-e29b-41d4-a716-446655440000")
            print(f"Agent: {agent_data['agent']['agent_name']}")
            print(f"Tools: {len(agent_data['tools'])}")
    """
    response = await client.http_client.get(f"/api/v1/agents/{agent_id}")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())

