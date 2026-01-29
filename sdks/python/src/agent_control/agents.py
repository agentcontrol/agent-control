"""Agent management operations for Agent Control SDK."""

from typing import Any, cast
from uuid import UUID

from agent_control_engine import ensure_evaluators_discovered

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
    steps: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """
    Register an agent with the server via /initAgent endpoint.

    Args:
        client: AgentControlClient instance
        agent: Agent instance to register
        steps: Optional list of step schemas

    Returns:
        InitAgentResponse with created flag and controls

    Raises:
        httpx.HTTPError: If request fails

    Example:
        async with AgentControlClient() as client:
            response = await register_agent(client, agent, steps=[...])
            print(f"Created: {response['created']}")
    """
    # Ensure evaluators are discovered for local evaluation support
    ensure_evaluators_discovered()

    if steps is None:
        steps = []

    if MODELS_AVAILABLE:
        agent_dict = agent.to_dict()
        # Ensure UUID is converted to string for JSON serialization
        if isinstance(agent_dict.get('agent_id'), UUID):
            agent_dict['agent_id'] = str(agent_dict['agent_id'])
        payload = {
            "agent": agent_dict,
            "steps": steps
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
            "steps": steps
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
            - steps: List of steps registered with the agent

    Raises:
        httpx.HTTPError: If request fails or agent not found (404)

    Example:
        async with AgentControlClient() as client:
            agent_data = await get_agent(client, "550e8400-e29b-41d4-a716-446655440000")
            print(f"Agent: {agent_data['agent']['agent_name']}")
            print(f"Steps: {len(agent_data['steps'])}")
    """
    response = await client.http_client.get(f"/api/v1/agents/{agent_id}")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def list_agents(
    client: AgentControlClient,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """
    List all registered agents from the server.

    Args:
        client: AgentControlClient instance
        cursor: Optional cursor for pagination (UUID of last agent from previous page)
        limit: Number of results per page (default 20, max 100)

    Returns:
        Dictionary containing:
            - agents: List of agent summaries with agent_id, agent_name,
                      policy_id, created_at, step_count, evaluator_count
            - pagination: Object with limit, total, next_cursor, has_more

    Raises:
        httpx.HTTPError: If request fails

    Example:
        async with AgentControlClient() as client:
            result = await list_agents(client, limit=10)
            print(f"Total agents: {result['pagination']['total']}")
            for agent in result['agents']:
                print(f"  - {agent['agent_name']} ({agent['agent_id']})")
            # Fetch next page if available
            if result['pagination']['has_more']:
                next_result = await list_agents(
                    client, cursor=result['pagination']['next_cursor']
                )
    """
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    response = await client.http_client.get("/api/v1/agents", params=params)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def get_agent_policy(
    client: AgentControlClient,
    agent_id: str,
) -> dict[str, Any]:
    """
    Get the policy assigned to an agent.

    Args:
        client: AgentControlClient instance
        agent_id: UUID or string identifier of the agent

    Returns:
        Dictionary containing:
            - policy_id: ID of the policy assigned to the agent

    Raises:
        httpx.HTTPError: If request fails or agent has no policy

    Example:
        async with AgentControlClient() as client:
            policy = await get_agent_policy(client, agent_id)
            print(f"Policy ID: {policy['policy_id']}")
    """
    response = await client.http_client.get(f"/api/v1/agents/{agent_id}/policy")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def remove_agent_policy(
    client: AgentControlClient,
    agent_id: str,
) -> dict[str, Any]:
    """
    Remove the policy assignment from an agent.

    Args:
        client: AgentControlClient instance
        agent_id: UUID or string identifier of the agent

    Returns:
        Dictionary containing success flag/details

    Raises:
        httpx.HTTPError: If request fails or agent has no policy
    """
    response = await client.http_client.delete(f"/api/v1/agents/{agent_id}/policy")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())
