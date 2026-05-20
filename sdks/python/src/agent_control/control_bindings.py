"""Control binding management operations for Agent Control SDK."""

from typing import Any, cast

from .client import AgentControlClient


async def upsert_control_binding_by_key(
    client: AgentControlClient,
    *,
    target_type: str,
    target_id: str,
    control_id: int,
    enabled: bool = True,
) -> dict[str, Any]:
    """Attach a control to a target, or update the existing binding."""
    response = await client.http_client.put(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": target_type,
            "target_id": target_id,
            "control_id": control_id,
            "enabled": enabled,
        },
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def update_control_binding_by_key(
    client: AgentControlClient,
    *,
    target_type: str,
    target_id: str,
    control_id: int,
    enabled: bool,
) -> dict[str, Any]:
    """Update an existing target binding without creating a missing binding."""
    response = await client.http_client.patch(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": target_type,
            "target_id": target_id,
            "control_id": control_id,
            "enabled": enabled,
        },
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def delete_control_binding_by_key(
    client: AgentControlClient,
    *,
    target_type: str,
    target_id: str,
    control_id: int,
) -> dict[str, Any]:
    """Detach a control from a target by natural key."""
    response = await client.http_client.post(
        "/api/v1/control-bindings/by-key:delete",
        json={
            "target_type": target_type,
            "target_id": target_id,
            "control_id": control_id,
        },
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())
