"""Agent management operations for Agent Control SDK."""

from typing import Any, Literal, cast

from agent_control_engine import ensure_evaluators_discovered
from agent_control_models import Agent
from agent_control_models.server import AgentControlsResponse

from .client import AgentControlClient
from .validation import ensure_agent_name


async def register_agent(
    client: AgentControlClient,
    agent: Agent,
    steps: list[dict[str, Any]] | None = None,
    conflict_mode: Literal["strict", "overwrite"] = "overwrite",
) -> dict[str, Any]:
    """Register an agent with the server via /initAgent endpoint."""
    ensure_evaluators_discovered()

    agent_dict = agent.to_dict()
    agent_dict["agent_name"] = ensure_agent_name(str(agent_dict.get("agent_name", "")))
    payload = {
        "agent": agent_dict,
        "steps": steps or [],
        "conflict_mode": conflict_mode,
    }

    response = await client.http_client.post("/api/v1/agents/initAgent", json=payload)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def get_agent(client: AgentControlClient, agent_name: str) -> dict[str, Any]:
    """Get agent details by name from the server."""
    normalized_name = ensure_agent_name(agent_name)
    response = await client.http_client.get(f"/api/v1/agents/{normalized_name}")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def list_agents(
    client: AgentControlClient,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List all registered agents from the server."""
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = ensure_agent_name(cursor)
    response = await client.http_client.get("/api/v1/agents", params=params)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def get_agent_policy(
    client: AgentControlClient,
    agent_name: str,
) -> dict[str, Any]:
    """Get the policy assigned to an agent."""
    normalized_name = ensure_agent_name(agent_name)
    response = await client.http_client.get(f"/api/v1/agents/{normalized_name}/policy")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def remove_agent_policy(
    client: AgentControlClient,
    agent_name: str,
) -> dict[str, Any]:
    """Remove the policy assignment from an agent."""
    normalized_name = ensure_agent_name(agent_name)
    response = await client.http_client.delete(f"/api/v1/agents/{normalized_name}/policy")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def list_agent_controls(
    client: AgentControlClient,
    agent_name: str,
) -> dict[str, Any]:
    """List active controls associated with an agent."""
    normalized_name = ensure_agent_name(agent_name)
    response = await client.http_client.get(f"/api/v1/agents/{normalized_name}/controls")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def list_agent_controls_typed(
    client: AgentControlClient,
    agent_name: str,
) -> AgentControlsResponse:
    """List active controls associated with an agent (typed response)."""
    normalized_name = ensure_agent_name(agent_name)
    response = await client.http_client.get(f"/api/v1/agents/{normalized_name}/controls")
    response.raise_for_status()
    return AgentControlsResponse.model_validate(response.json())
