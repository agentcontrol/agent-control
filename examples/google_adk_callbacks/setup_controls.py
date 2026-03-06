#!/usr/bin/env python3
"""Create controls for the Google ADK callbacks example."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from agent_control import Agent, AgentControlClient, agents, controls

AGENT_NAME = "google-adk-callbacks"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

CONTROL_SPECS: list[tuple[str, dict[str, Any]]] = [
    (
        "adk-callbacks-block-prompt-injection",
        {
            "description": "Block prompt injection patterns before the ADK model call",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": (
                        r"(?i)(ignore.{0,20}(previous|prior|above).{0,20}instructions"
                        r"|system:|forget everything|reveal secrets)"
                    )
                },
            },
            "action": {
                "decision": "deny",
                "message": "Prompt injection attempt detected.",
            },
        },
    ),
    (
        "adk-callbacks-block-restricted-cities",
        {
            "description": "Block requests for restricted cities before tool execution",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["get_current_time", "get_weather"],
                "stages": ["pre"],
            },
            "selector": {"path": "input.city"},
            "evaluator": {
                "name": "list",
                "config": {
                    "values": ["Pyongyang", "Tehran", "Damascus"],
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
    (
        "adk-callbacks-block-internal-contact-output",
        {
            "description": "Block internal contact details in tool output",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["get_current_time", "get_weather"],
                "stages": ["post"],
            },
            "selector": {"path": "output.note"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"support@internal\.example|123-45-6789",
                },
            },
            "action": {
                "decision": "deny",
                "message": "Tool output exposed internal contact data.",
            },
        },
    ),
]


async def _ensure_control(
    client: AgentControlClient,
    name: str,
    data: dict[str, Any],
) -> int:
    """Create the control or update the existing definition."""
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
    """Register the example agent and create its controls."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        await client.health_check()

        agent = Agent(
            agent_name=AGENT_NAME,
            agent_description="Google ADK example using Agent Control callbacks",
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
        print("Google ADK callbacks example is ready.")
        print("Run: uv run adk run my_agent")


if __name__ == "__main__":
    asyncio.run(main())
