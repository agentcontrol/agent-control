#!/usr/bin/env python3
"""Create controls for the Google ADK packaged-plugin example."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

import httpx
from agent_control import Agent, AgentControlClient, agents, controls

AGENT_NAME = "google-adk-plugin"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
TOOL_STEP_NAMES = [
    "root_agent.get_current_time",
    "root_agent.get_weather",
]


def _control_specs(execution: str) -> list[tuple[str, dict[str, Any]]]:
    """Build control definitions for the requested execution mode."""
    return [
        (
            "adk-plugin-block-prompt-injection",
            {
                "description": "Block prompt injection patterns before the ADK model call",
                "enabled": True,
                "execution": execution,
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
            "adk-plugin-block-restricted-cities",
            {
                "description": "Block requests for restricted cities before tool execution",
                "enabled": True,
                "execution": execution,
                "scope": {
                    "step_types": ["tool"],
                    "step_names": TOOL_STEP_NAMES,
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
            "adk-plugin-block-internal-contact-output",
            {
                "description": "Block internal contact details in tool output",
                "enabled": True,
                "execution": execution,
                "scope": {
                    "step_types": ["tool"],
                    "step_names": TOOL_STEP_NAMES,
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


async def main(execution: str) -> None:
    """Register the example agent and create its controls."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        await client.health_check()

        agent = Agent(
            agent_name=AGENT_NAME,
            agent_description="Google ADK example using the packaged Agent Control plugin",
        )
        await agents.register_agent(client, agent, steps=[])

        control_ids: list[int] = []
        for control_name, control_data in _control_specs(execution):
            control_id = await _ensure_control(client, control_name, control_data)
            control_ids.append(control_id)
            print(f"Prepared control: {control_name} ({control_id}) [{execution}]")

        for control_id in control_ids:
            try:
                await agents.add_agent_control(client, AGENT_NAME, control_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 409:
                    raise

        print()
        print("Google ADK plugin example is ready.")
        print("Run: uv run adk run my_agent")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set up the Google ADK plugin example")
    parser.add_argument(
        "--execution",
        choices=["server", "sdk"],
        default="server",
        help="Where the example controls should execute.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.execution))
