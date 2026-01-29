"""Control management operations for Agent Control SDK."""

from typing import Any, Literal, cast

# Import models if available
try:
    from agent_control_models import ControlDefinition

    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    ControlDefinition = Any  # type: ignore

from .client import AgentControlClient


async def list_controls(
    client: AgentControlClient,
    cursor: int | None = None,
    limit: int = 20,
    name: str | None = None,
    enabled: bool | None = None,
    step_type: str | None = None,
    stage: Literal["pre", "post"] | None = None,
    execution: Literal["server", "sdk"] | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """
    List all controls with optional filtering and pagination.

    Controls are returned ordered by ID descending (newest first).

    Args:
        client: AgentControlClient instance
        cursor: Control ID to start after (for pagination)
        limit: Maximum number of controls to return (default 20, max 100)
        name: Optional filter by name (partial, case-insensitive match)
        enabled: Optional filter by enabled status
        step_type: Optional filter by step type (built-ins: 'tool', 'llm')
        stage: Optional filter by stage ('pre' or 'post')
        execution: Optional filter by execution ('server' or 'sdk')
        tag: Optional filter by tag

    Returns:
        Dictionary containing:
            - controls: List of control summaries with id, name, description,
                       enabled, execution, step_types, stages, tags
            - pagination: Object with limit, total, next_cursor, has_more

    Raises:
        httpx.HTTPError: If request fails

    Example:
        async with AgentControlClient() as client:
            # List all controls
            result = await list_controls(client)
            print(f"Total: {result['pagination']['total']}")

            # Filter by type
            llm_controls = await list_controls(client, step_type="llm")

            # Paginate
            page1 = await list_controls(client, limit=10)
            if page1['pagination']['has_more']:
                page2 = await list_controls(
                    client,
                    cursor=int(page1['pagination']['next_cursor']),
                    limit=10
                )
    """
    params: dict[str, Any] = {"limit": limit}
    if cursor is not None:
        params["cursor"] = cursor
    if name is not None:
        params["name"] = name
    if enabled is not None:
        params["enabled"] = enabled
    if step_type is not None:
        params["step_type"] = step_type
    if stage is not None:
        params["stage"] = stage
    if execution is not None:
        params["execution"] = execution
    if tag is not None:
        params["tag"] = tag

    response = await client.http_client.get("/api/v1/controls", params=params)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def get_control(
    client: AgentControlClient,
    control_id: int,
) -> dict[str, Any]:
    """
    Get a control by ID.

    Args:
        client: AgentControlClient instance
        control_id: ID of the control

    Returns:
        Dictionary containing:
            - id: Control ID
            - name: Control name
            - data: Control definition (selector, evaluator, action) or None if not configured

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control not found

    Example:
        async with AgentControlClient() as client:
            control = await get_control(client, control_id=5)
            print(f"Control: {control['name']}")
            if control['data']:
                print(f"Execution: {control['data']['execution']}")
    """
    response = await client.http_client.get(f"/api/v1/controls/{control_id}")
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def create_control(
    client: AgentControlClient,
    name: str,
    data: dict[str, Any] | ControlDefinition | None = None,
) -> dict[str, Any]:
    """
    Create a new control with a unique name, optionally with configuration.

    If `data` is provided, the control is created and configured in one call.
    Otherwise, use `set_control_data()` to configure it later.

    Args:
        client: AgentControlClient instance
        name: Unique name for the control
        data: Optional control definition (selector, evaluator, action, etc.)

    Returns:
        Dictionary containing:
            - control_id: ID of the created control
            - configured: True if data was set, False if only name was created

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 409: Control with this name already exists
        HTTPException 422: If data doesn't match schema
        HTTPException 500: Database error during creation

    Example:
        async with AgentControlClient() as client:
            # Create without configuration (configure later)
            result = await create_control(client, "pii-protection")
            control_id = result["control_id"]

            # Or create with configuration in one call
            result = await create_control(
                client,
                name="ssn-blocker",
                data={
                    "execution": "server",
                    "scope": {"step_types": ["llm"], "stages": ["post"]},
                    "selector": {"path": "output"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": r"\\d{3}-\\d{2}-\\d{4}"}
                    },
                    "action": {"decision": "deny"}
                }
            )
            print(f"Created and configured control: {result['control_id']}")
    """
    # Step 1: Create the control with name
    response = await client.http_client.put(
        "/api/v1/controls",
        json={"name": name}
    )
    response.raise_for_status()
    result = cast(dict[str, Any], response.json())

    # Step 2: If data provided, configure the control
    if data is not None:
        control_id = result["control_id"]
        await set_control_data(client, control_id, data)
        result["configured"] = True
    else:
        result["configured"] = False

    return result


async def set_control_data(
    client: AgentControlClient,
    control_id: int,
    data: dict[str, Any] | ControlDefinition
) -> dict[str, Any]:
    """
    Set the configuration data for a control.

    This defines what the control actually does (selector, evaluator, action).

    Args:
        client: AgentControlClient instance
        control_id: ID of the control
        data: Control definition dictionary or Pydantic model

    Returns:
        Dictionary containing success flag

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 422: If data doesn't match schema
    """
    if MODELS_AVAILABLE and isinstance(data, ControlDefinition):
        # Convert model to dict, excluding None to keep payload clean
        payload: dict[str, Any] = data.model_dump(mode="json", exclude_none=True)
    else:
        # We assume it's a dict if it's not a model
        payload = cast(dict[str, Any], data)

    response = await client.http_client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": payload}
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def add_rule_to_control(
    client: AgentControlClient,
    control_id: int,
    rule_id: int
) -> dict[str, Any]:
    """
    Associate a rule with a control.

    This operation is idempotent - adding the same rule multiple times has no effect.
    Agents with policies containing this control will immediately see the added rule.

    Args:
        client: AgentControlClient instance
        control_id: ID of the control
        rule_id: ID of the rule to add

    Returns:
        Dictionary containing:
            - success: True if operation succeeded

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control or rule not found
        HTTPException 500: Database error

    Example:
        async with AgentControlClient() as client:
            result = await add_rule_to_control(client, control_id=5, rule_id=10)
            print(f"Success: {result['success']}")
    """
    response = await client.http_client.post(
        f"/api/v1/controls/{control_id}/rules/{rule_id}"
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def remove_rule_from_control(
    client: AgentControlClient,
    control_id: int,
    rule_id: int
) -> dict[str, Any]:
    """
    Remove a rule from a control.

    This operation is idempotent - removing a non-associated rule has no effect.
    Agents with policies containing this control will immediately lose the removed rule.

    Args:
        client: AgentControlClient instance
        control_id: ID of the control
        rule_id: ID of the rule to remove

    Returns:
        Dictionary containing:
            - success: True if operation succeeded

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control or rule not found
        HTTPException 500: Database error

    Example:
        async with AgentControlClient() as client:
            result = await remove_rule_from_control(client, control_id=5, rule_id=10)
            print(f"Success: {result['success']}")
    """
    response = await client.http_client.delete(
        f"/api/v1/controls/{control_id}/rules/{rule_id}"
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def list_control_rules(
    client: AgentControlClient,
    control_id: int
) -> dict[str, Any]:
    """
    List all rules associated with a control.

    Args:
        client: AgentControlClient instance
        control_id: ID of the control

    Returns:
        Dictionary containing:
            - rule_ids: List of rule IDs associated with the control

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control not found

    Example:
        async with AgentControlClient() as client:
            result = await list_control_rules(client, control_id=5)
            rule_ids = result["rule_ids"]
            print(f"Control has {len(rule_ids)} rules: {rule_ids}")
    """
    response = await client.http_client.get(
        f"/api/v1/controls/{control_id}/rules"
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def delete_control(
    client: AgentControlClient,
    control_id: int,
    force: bool = False,
) -> dict[str, Any]:
    """
    Delete a control by ID.

    By default, deletion fails if the control is associated with any policy.
    Use force=True to automatically dissociate and delete.

    Args:
        client: AgentControlClient instance
        control_id: ID of the control to delete
        force: If True, remove associations before deleting

    Returns:
        Dictionary containing:
            - success: True if control was deleted
            - dissociated_from: List of policy IDs the control was removed from

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control not found
        HTTPException 409: Control is in use (and force=False)

    Example:
        async with AgentControlClient() as client:
            # Try to delete (fails if in use)
            try:
                result = await delete_control(client, control_id=5)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 409:
                    # Force delete
                    result = await delete_control(client, control_id=5, force=True)
                    print(f"Removed from {len(result['dissociated_from'])} policies")
    """
    params = {"force": force}
    response = await client.http_client.delete(
        f"/api/v1/controls/{control_id}",
        params=params,
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def update_control(
    client: AgentControlClient,
    control_id: int,
    name: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """
    Update control metadata (name and/or enabled status).

    This endpoint allows partial updates - only provide the fields you want to change.

    Args:
        client: AgentControlClient instance
        control_id: ID of the control to update
        name: New name for the control (optional)
        enabled: Enable or disable the control (optional, requires control to have data)

    Returns:
        Dictionary containing:
            - success: True if update succeeded
            - name: Current control name (may have changed)
            - enabled: Current enabled status (if control has data)

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control not found
        HTTPException 409: New name conflicts with existing control
        HTTPException 422: Cannot update enabled (control has no data configured)

    Example:
        async with AgentControlClient() as client:
            # Rename a control
            result = await update_control(client, control_id=5, name="new-name")

            # Disable a control
            result = await update_control(client, control_id=5, enabled=False)

            # Both at once
            result = await update_control(
                client,
                control_id=5,
                name="pii-protection-v2",
                enabled=True
            )
    """
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if enabled is not None:
        payload["enabled"] = enabled

    response = await client.http_client.patch(
        f"/api/v1/controls/{control_id}",
        json=payload,
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())
