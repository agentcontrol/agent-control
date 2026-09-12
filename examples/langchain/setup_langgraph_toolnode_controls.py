"""Create controls for the LangGraph ToolNode integration smoke test.

This script prepares a single direct agent control for the
``langgraph_toolnode_integration_smoke.py`` example.

Run:
    cd examples/langchain
    uv run setup_langgraph_toolnode_controls.py
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from agent_control import Agent, AgentControlClient, agents, controls

AGENT_NAME = "langgraph-toolnode-smoke"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

CONTROL_SPECS: list[tuple[str, dict[str, Any]]] = [
    (
        "langgraph-toolnode-block-city",
        {
            "description": "Block restricted cities before the get_weather tool runs.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["get_weather"],
                "stages": ["pre"],
            },
            "selector": {"path": "input.city"},
            "evaluator": {
                "name": "list",
                "config": {
                    "values": ["Tehran", "Pyongyang"],
                    "logic": "any",
                    "match_on": "match",
                    "match_mode": "exact",
                    "case_sensitive": False,
                },
            },
            "action": {
                "decision": "deny",
                "message": "That city is blocked by policy.",
            },
        },
    ),
]


async def _ensure_control(
    client: AgentControlClient,
    name: str,
    data: dict[str, Any],
) -> int:
    """Create a control or update the existing definition."""
    try:
        result = await controls.create_control(client, name=name, data=data)
        return int(result["control_id"])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise

    control_list = await controls.list_controls(client, name=name, limit=1)
    existing = control_list.get("controls", [])
    if not existing:
        raise RuntimeError(f"Control '{name}' already exists but could not be listed.")

    control_id = int(existing[0]["id"])
    await controls.set_control_data(client, control_id, data)
    return control_id


async def main() -> None:
    """Register the example agent and ensure its controls exist."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        await client.health_check()

        agent = Agent(
            agent_name=AGENT_NAME,
            agent_description="LangGraph ToolNode smoke test using Agent Control integration",
        )
        await agents.register_agent(client, agent, steps=[])

        control_ids: list[int] = []
        for control_name, control_data in CONTROL_SPECS:
            control_id = await _ensure_control(client, control_name, control_data)
            control_ids.append(control_id)
            print(f"Prepared control: {control_name} ({control_id})")

        for control_id in control_ids:
            try:
                await agents.add_agent_control(client, AGENT_NAME, control_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 409:
                    raise

        print()
        print("LangGraph ToolNode smoke test is ready.")
        print("Run: uv run langgraph_toolnode_integration_smoke.py")


if __name__ == "__main__":
    asyncio.run(main())
