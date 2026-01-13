"""Policy management operations for Agent Control SDK."""

from typing import Any, cast

from .client import AgentControlClient


async def create_policy(
    client: AgentControlClient,
    name: str
) -> dict[str, Any]:
    """
    Create a new policy with a unique name.

    Policies group controls together and can be assigned to agents.
    A newly created policy has no controls until they are explicitly added.

    Args:
        client: AgentControlClient instance
        name: Unique name for the policy

    Returns:
        Dictionary containing:
            - policy_id: ID of the created policy

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 409: Policy with this name already exists
        HTTPException 500: Database error during creation

    Example:
        async with AgentControlClient() as client:
            result = await create_policy(client, "production-policy")
            policy_id = result["policy_id"]
            print(f"Created policy with ID: {policy_id}")
    """
    response = await client.http_client.put(
        "/api/v1/policies",
        json={"name": name}
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def add_control_to_policy(
    client: AgentControlClient,
    policy_id: int,
    control_id: int
) -> dict[str, Any]:
    """
    Associate a control with a policy.

    This operation is idempotent - adding the same control multiple times has no effect.
    Agents with this policy will immediately see the added control.

    Args:
        client: AgentControlClient instance
        policy_id: ID of the policy
        control_id: ID of the control to add

    Returns:
        Dictionary containing:
            - success: True if operation succeeded

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Policy or control not found
        HTTPException 500: Database error

    Example:
        async with AgentControlClient() as client:
            result = await add_control_to_policy(client, policy_id=1, control_id=5)
            print(f"Success: {result['success']}")
    """
    response = await client.http_client.post(
        f"/api/v1/policies/{policy_id}/controls/{control_id}"
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def remove_control_from_policy(
    client: AgentControlClient,
    policy_id: int,
    control_id: int
) -> dict[str, Any]:
    """
    Remove a control from a policy.

    This operation is idempotent - removing a non-associated control has no effect.
    Agents with this policy will immediately lose the removed control.

    Args:
        client: AgentControlClient instance
        policy_id: ID of the policy
        control_id: ID of the control to remove

    Returns:
        Dictionary containing:
            - success: True if operation succeeded

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Policy or control not found
        HTTPException 500: Database error

    Example:
        async with AgentControlClient() as client:
            result = await remove_control_from_policy(client, policy_id=1, control_id=5)
            print(f"Success: {result['success']}")
    """
    response = await client.http_client.delete(
        f"/api/v1/policies/{policy_id}/controls/{control_id}"
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def list_policy_controls(
    client: AgentControlClient,
    policy_id: int
) -> dict[str, Any]:
    """
    List all controls associated with a policy.

    Args:
        client: AgentControlClient instance
        policy_id: ID of the policy

    Returns:
        Dictionary containing:
            - control_ids: List of control IDs associated with the policy

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Policy not found

    Example:
        async with AgentControlClient() as client:
            result = await list_policy_controls(client, policy_id=1)
            control_ids = result["control_ids"]
            print(f"Policy has {len(control_ids)} controls: {control_ids}")
    """
    response = await client.http_client.get(
        f"/api/v1/policies/{policy_id}/controls"
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def assign_policy_to_agent(
    client: AgentControlClient,
    agent_id: str,
    policy_id: int
) -> dict[str, Any]:
    """
    Assign a policy to an agent.

    This makes the policy active for the agent. Any existing policy assignment is replaced.

    Args:
        client: AgentControlClient instance
        agent_id: UUID or string identifier of the agent
        policy_id: ID of the policy to assign

    Returns:
        Dictionary containing success flag/details

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Agent or policy not found
    """
    response = await client.http_client.post(
        f"/api/v1/agents/{agent_id}/policy/{policy_id}"
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())

