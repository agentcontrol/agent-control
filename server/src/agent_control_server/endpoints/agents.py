from typing import Any
from uuid import UUID

from agent_control_models.agent import Agent as APIAgent
from agent_control_models.agent import AgentTool
from agent_control_models.server import (
    AgentControlsResponse,
    DeletePolicyResponse,
    GetAgentResponse,
    GetPolicyResponse,
    InitAgentRequest,
    InitAgentResponse,
    SetPolicyResponse,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic_core._pydantic_core import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..logging_utils import get_logger
from ..models import Agent, AgentData, AgentVersionedTool, Policy
from ..schema_generator import generate_agent_schema, validate_agent_schema
from ..services.controls import list_controls_for_agent

router = APIRouter(prefix="/agents", tags=["agents"])

_logger = get_logger(__name__)


@router.post(
    "/initAgent",
    response_model=InitAgentResponse,
    summary="Initialize or update an agent",
    response_description="Agent registration status with active controls",
)
async def init_agent(
    request: InitAgentRequest, db: AsyncSession = Depends(get_async_db)
) -> InitAgentResponse:
    """
    Register a new agent or update an existing agent's tools and metadata.

    This endpoint is idempotent:
    - If the agent name doesn't exist, creates a new agent
    - If the agent name exists with the same UUID, updates tool schemas
    - If the agent name exists with a different UUID, returns 409 Conflict

    Tool versioning: When tool schemas change (arguments or output_schema),
    a new version is created automatically.

    Args:
        request: Agent metadata and tool schemas
        db: Database session (injected)

    Returns:
        InitAgentResponse with created flag and active controls (if policy assigned)

    Raises:
        HTTPException 409: Agent name exists with different UUID
        HTTPException 500: Database error during creation/update
    """
    # Look up by name only; name is unique
    result = await db.execute(select(Agent).where(Agent.name == request.agent.agent_name))
    existing: Agent | None = result.scalars().first()

    created = False

    if existing is None:
        created = True
        versioned_tools = [
            AgentVersionedTool(version=0, tool=tool) for tool in request.tools
        ]

        # Generate agent schema from tools
        tools_dict = [tool.model_dump(mode="json") for tool in request.tools]
        agent_schema = generate_agent_schema(tools_dict)

        # Validate generated schema
        is_valid, errors = validate_agent_schema(agent_schema)
        if not is_valid:
            _logger.warning(
                f"Generated schema validation failed for agent "
                f"'{request.agent.agent_name}': {errors}"
            )

        data_model = AgentData(
            agent_metadata=request.agent.model_dump(mode="json"),
            tools=versioned_tools,
            agent_schema=agent_schema,  # Include schema in the model
        )

        new_agent = Agent(
            name=request.agent.agent_name,
            agent_uuid=request.agent.agent_id,
            data=data_model.model_dump(mode="json"),
        )
        db.add(new_agent)
        try:
            await db.commit()
            _logger.info(
                f"Created agent '{request.agent.agent_name}' with {len(request.tools)} tools "
                f"and auto-generated schema"
            )
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to create agent '{request.agent.agent_name}' ({request.agent.agent_id})",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create agent '{request.agent.agent_name}': database error",
            )
        return InitAgentResponse(created=created, controls=[])

    requested_uuid = request.agent.agent_id
    if existing.agent_uuid != requested_uuid:
        # UUID mismatch for the same name: return error
        raise HTTPException(
            status_code=409,
            detail=f"Agent name '{request.agent.agent_name}' already exists with different UUID",
        )

    # Parse existing data via AgentData Pydantic model
    try:
        data_model = AgentData.model_validate(existing.data)
    except ValidationError:
        _logger.warning(
            f"Failed to parse existing agent data for '{request.agent.agent_name}'",
            exc_info=True,
        )
        data_model = AgentData(agent_metadata={}, tools=[])

    changed = False

    incoming_by_name: dict[str, AgentTool] = {t.tool_name: t for t in request.tools}
    new_tools: list[AgentVersionedTool] = []
    seen: set[str] = set()

    for vt in data_model.tools or []:
        name = vt.tool.tool_name
        if name in incoming_by_name:
            if name not in seen:
                incoming_tool = incoming_by_name[name]
                if vt.tool.model_dump(mode="json") != incoming_tool.model_dump(mode="json"):
                    changed = True
                new_tools.append(AgentVersionedTool(version=0, tool=incoming_tool))
                seen.add(name)
        else:
            new_tools.append(vt)

    for name, t in incoming_by_name.items():
        if name not in seen and all((x.tool.tool_name != name) for x in new_tools):
            new_tools.append(AgentVersionedTool(version=0, tool=t))
            changed = True

    data_model.tools = new_tools

    if changed:
        # Regenerate schema when tools change
        tools_dict = [vt.tool.model_dump(mode="json") for vt in new_tools]
        agent_schema = generate_agent_schema(tools_dict)

        # Validate generated schema
        is_valid, errors = validate_agent_schema(agent_schema)
        if not is_valid:
            _logger.warning(
                f"Generated schema validation failed for agent "
                f"'{request.agent.agent_name}': {errors}"
            )

        # Update the data model with new schema
        data_model.agent_schema = agent_schema
        existing.data = data_model.model_dump(mode="json")

        try:
            await db.commit()
            _logger.info(
                f"Updated agent '{request.agent.agent_name}' with {len(new_tools)} tools "
                f"and regenerated schema"
            )
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to update agent '{request.agent.agent_name}' ({request.agent.agent_id})",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update agent '{request.agent.agent_name}': database error",
            )

    # If the existing agent has a policy, include its controls; otherwise empty list
    controls = []
    if existing.policy_id is not None:
        controls = await list_controls_for_agent(existing.agent_uuid, db)

    # Auto-create policies requested by the agent (e.g. via @control decorators)
    if request.policies:
        for policy_name in request.policies:
            # Check if policy exists
            p_result = await db.execute(select(Policy).where(Policy.name == policy_name))
            policy = p_result.scalars().first()

            if not policy:
                # Create empty policy
                new_policy = Policy(name=policy_name)
                db.add(new_policy)
                _logger.info(
                    f"Auto-created missing policy '{policy_name}' "
                    f"requested by agent '{request.agent.agent_name}'"
                )

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to auto-create policies for agent '{request.agent.agent_name}'",
                exc_info=True
            )
            # We don't raise here to allow agent registration to succeed
            # even if policy creation fails

    return InitAgentResponse(created=created, controls=controls)


@router.get(
    "/{agent_id}",
    response_model=GetAgentResponse,
    summary="Get agent details",
    response_description="Agent metadata and registered tools",
)
async def get_agent(agent_id: UUID, db: AsyncSession = Depends(get_async_db)) -> GetAgentResponse:
    """
    Retrieve agent metadata and all registered tools.

    Returns the latest version of each tool (tools are deduplicated by name).

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        GetAgentResponse with agent metadata and tool list

    Raises:
        HTTPException 404: Agent not found
        HTTPException 422: Agent data is corrupted
    """
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    existing: Agent | None = result.scalars().first()
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"Agent with ID '{agent_id}' not found"
        )

    try:
        data_model = AgentData.model_validate(existing.data)
    except ValidationError:
        _logger.error(
            f"Failed to parse agent data for agent '{existing.name}' ({agent_id})",
            exc_info=True,
        )
        raise HTTPException(
            status_code=422,
            detail=f"Agent data is corrupted for agent '{existing.name}'",
        )

    try:
        tools_by_name: dict[str, AgentTool] = {}
        for vt in data_model.tools or []:
            tools_by_name[vt.tool.tool_name] = vt.tool
        latest_tools: list[AgentTool] = list(tools_by_name.values())
        agent_meta = APIAgent.model_validate(data_model.agent_metadata)
    except ValidationError:
        _logger.error(
            f"Failed to parse agent metadata for agent '{existing.name}' ({agent_id})",
            exc_info=True,
        )
        raise HTTPException(
            status_code=422,
            detail=f"Agent metadata is corrupted for agent '{existing.name}'",
        )

    return GetAgentResponse(agent=agent_meta, tools=latest_tools)


@router.post(
    "/{agent_id}/policy/{policy_id}",
    response_model=SetPolicyResponse,
    summary="Assign policy to agent",
    response_description="Success status with previous policy ID",
)
async def set_agent_policy(
    agent_id: UUID, policy_id: int, db: AsyncSession = Depends(get_async_db)
) -> SetPolicyResponse:
    """
    Assign a policy to an agent, replacing any existing policy assignment.

    The agent will immediately inherit all controls from control sets in the assigned policy.

    Args:
        agent_id: UUID of the agent
        policy_id: ID of the policy to assign
        db: Database session (injected)

    Returns:
        SetPolicyResponse with success flag and previous policy ID (if any)

    Raises:
        HTTPException 404: Agent or policy not found
        HTTPException 500: Database error during assignment
    """
    # Find agent
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent with ID '{agent_id}' not found"
        )

    # Find policy by id
    policy_result = await db.execute(select(Policy).where(Policy.id == policy_id))
    policy: Policy | None = policy_result.scalars().first()
    if policy is None:
        raise HTTPException(
            status_code=404, detail=f"Policy with ID '{policy_id}' not found"
        )

    # Store old policy ID if exists
    old_policy_id: int | None = None
    if agent.policy_id is not None:
        old_policy_id = agent.policy_id

    # Assign new policy
    agent.policy_id = policy.id
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to assign policy '{policy_id}' to agent '{agent.name}' ({agent_id})",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to assign policy to agent '{agent.name}': database error",
        )

    return SetPolicyResponse(success=True, old_policy_id=old_policy_id)


@router.get(
    "/{agent_id}/policy",
    response_model=GetPolicyResponse,
    summary="Get agent's assigned policy",
    response_description="Policy ID",
)
async def get_agent_policy(
    agent_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> GetPolicyResponse:
    """
    Retrieve the policy currently assigned to an agent.

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        GetPolicyResponse with policy ID

    Raises:
        HTTPException 404: Agent not found or agent has no policy assigned
    """
    # Find agent
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent with ID '{agent_id}' not found"
        )

    # Check if agent has a policy
    if agent.policy_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent.name}' has no policy assigned",
        )

    # Find policy
    policy_result = await db.execute(select(Policy).where(Policy.id == agent.policy_id))
    policy: Policy | None = policy_result.scalars().first()
    if policy is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Policy with ID '{agent.policy_id}' not found "
                f"(referenced by agent '{agent.name}')"
            ),
        )

    return GetPolicyResponse(policy_id=policy.id)


@router.delete(
    "/{agent_id}/policy",
    response_model=DeletePolicyResponse,
    summary="Remove agent's policy assignment",
    response_description="Success confirmation",
)
async def delete_agent_policy(
    agent_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> DeletePolicyResponse:
    """
    Remove the policy assignment from an agent.

    The agent will no longer have any protection controls active.

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        DeletePolicyResponse with success flag

    Raises:
        HTTPException 404: Agent not found or agent has no policy assigned
        HTTPException 500: Database error during removal
    """
    # Find agent
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent with ID '{agent_id}' not found"
        )

    # Check if agent has a policy
    if agent.policy_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent.name}' has no policy assigned",
        )

    # Remove policy assignment
    agent.policy_id = None
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to remove policy from agent '{agent.name}' ({agent_id})",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove policy from agent '{agent.name}': database error",
        )

    return DeletePolicyResponse(success=True)


@router.get(
    "/{agent_id}/controls",
    response_model=AgentControlsResponse,
    summary="List agent's active controls",
    response_description="List of controls from agent's policy",
)
async def list_agent_controls(
    agent_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> AgentControlsResponse:
    """
    List all protection controls active for an agent.

    Controls are inherited from all control sets in the agent's assigned policy.
    Returns an empty list if the agent has no policy.

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        AgentControlsResponse with list of controls (empty if no policy)

    Raises:
        HTTPException 404: Agent not found
    """
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent with ID '{agent_id}' not found"
        )

    if agent.policy_id is None:
        return AgentControlsResponse(controls=[])

    controls = await list_controls_for_agent(agent_id, db)
    return AgentControlsResponse(controls=controls)


@router.get(
    "/{agent_id}/schema",
    summary="Get agent's auto-generated schema",
    response_description="Schema generated from registered tools",
)
async def get_agent_schema(
    agent_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> dict[str, Any]:
    """
    Retrieve the auto-generated schema for an agent.

    The schema is automatically generated from the agent's registered tools
    and includes:
    - Tool definitions with input/output schemas
    - Extracted capabilities
    - Validation rules

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        Auto-generated agent schema

    Raises:
        HTTPException 404: Agent not found or no schema available
    """
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent with ID '{agent_id}' not found"
        )

    # Extract schema from agent data
    schema = agent.data.get("agent_schema")
    if schema is None:
        # Check if agent has tools - if so, we can generate schema on-demand
        try:
            data_model = AgentData.model_validate(agent.data)
            if data_model.tools:
                # Generate schema from existing tools for backward compatibility
                _logger.info(f"Generating schema for legacy agent '{agent.name}'")
                tools_dict = [vt.tool.model_dump(mode="json") for vt in data_model.tools]
                schema = generate_agent_schema(tools_dict)

                # Optionally persist it for next time
                data_model.agent_schema = schema
                agent.data = data_model.model_dump(mode="json")
                await db.commit()
                _logger.info(f"Persisted auto-generated schema for agent '{agent.name}'")

                return schema
        except ValidationError:
            _logger.error(f"Failed to parse agent data for '{agent.name}'", exc_info=True)

        raise HTTPException(
            status_code=404,
            detail=f"No schema available for agent '{agent.name}'. "
                   f"Schema is auto-generated when agents are registered with tools."
        )

    # Cast to satisfy mypy since we know schema is dict[str, Any] at this point
    return dict(schema)
