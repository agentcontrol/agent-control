#!/usr/bin/env python3
"""Create the controls used by the OTEL merged-events demo."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

from agent_control import AgentControlClient


AGENT_NAME = "otel-merged-events-demo-agent"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def create_agent(client: AgentControlClient) -> None:
    """Create or fetch the demo agent.

    Args:
        client: Configured Agent Control client.

    Returns:
        None.
    """
    response = await client.http_client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {
                "agent_name": AGENT_NAME,
                "agent_description": "Demo agent for OTEL merged-event emission",
            },
            "steps": [],
        },
    )
    response.raise_for_status()
    created = response.json().get("created", False)
    label = "Created" if created else "Fetched"
    print(f"{label} agent: {AGENT_NAME}")


async def create_control(
    client: AgentControlClient,
    name: str,
    control_definition: dict[str, object],
) -> int:
    """Create a control and return its ID.

    Args:
        client: Configured Agent Control client.
        name: Control name.
        control_definition: Control definition payload.

    Returns:
        The created control ID.
    """
    response = await client.http_client.put(
        "/api/v1/controls",
        json={"name": name, "data": control_definition},
    )
    control_exists = response.status_code == 409
    if control_exists:
        response = await client.http_client.get("/api/v1/controls", params={"name": name})
        response.raise_for_status()
        controls = [
            control
            for control in response.json().get("controls", [])
            if control.get("name") == name
        ]
        if not controls:
            raise RuntimeError(f"Could not find existing control named '{name}'")

        control_id = controls[0]["id"]
        response = await client.http_client.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": control_definition},
        )
        response.raise_for_status()
        print(f"Updated existing control '{name}' with id {control_id}")
        return control_id

    response.raise_for_status()
    control_id = response.json()["control_id"]
    print(f"Created control '{name}' with id {control_id}")
    return control_id


async def attach_control(
    client: AgentControlClient,
    control_id: int,
) -> None:
    """Attach a control to the demo agent.

    Args:
        client: Configured Agent Control client.
        control_id: Control ID to attach.

    Returns:
        None.
    """
    response = await client.http_client.post(
        f"/api/v1/agents/{AGENT_NAME}/controls/{control_id}"
    )
    if response.status_code not in (200, 409):
        response.raise_for_status()
    print(f"Attached control {control_id} to agent {AGENT_NAME}")


async def main() -> None:
    """Create the demo controls.

    Args:
        None.

    Returns:
        None.
    """
    async with AgentControlClient(base_url=SERVER_URL) as client:
        await create_agent(client)

        local_control_id = await create_control(
            client,
            "otel-merged-local-input-check",
            {
                "description": (
                    "SDK-local composite control for merged OTEL event export demo"
                ),
                "enabled": True,
                "execution": "sdk",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "and": [
                        {
                            "selector": {"path": "input"},
                            "evaluator": {
                                "name": "regex",
                                "config": {"pattern": "local-trigger", "flags": []},
                            },
                        },
                        {
                            "selector": {"path": "input"},
                            "evaluator": {
                                "name": "list",
                                "config": {
                                    "values": ["priority"],
                                    "logic": "any",
                                    "match_on": "match",
                                    "match_mode": "contains",
                                    "case_sensitive": False,
                                },
                            },
                        },
                    ]
                },
                "action": {"decision": "allow"},
                "tags": ["otel", "merged-events", "sdk"],
            },
        )

        server_control_id = await create_control(
            client,
            "otel-merged-server-input-check",
            {
                "description": (
                    "Server-side composite control for merged OTEL event export demo"
                ),
                "enabled": True,
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "and": [
                        {
                            "selector": {"path": "input"},
                            "evaluator": {
                                "name": "list",
                                "config": {
                                    "values": ["server-trigger"],
                                    "logic": "any",
                                    "match_on": "match",
                                    "match_mode": "contains",
                                    "case_sensitive": False,
                                },
                            },
                        },
                        {
                            "selector": {"path": "input"},
                            "evaluator": {
                                "name": "regex",
                                "config": {"pattern": "elevated", "flags": []},
                            },
                        },
                    ]
                },
                "action": {"decision": "allow"},
                "tags": ["otel", "merged-events", "server"],
            },
        )

        await attach_control(client, local_control_id)
        await attach_control(client, server_control_id)

        print("\nSetup complete.")
        print("Run demo_agent.py to trigger both controls and collect OTEL spans.")


if __name__ == "__main__":
    asyncio.run(main())
