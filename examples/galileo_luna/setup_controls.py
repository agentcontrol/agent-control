#!/usr/bin/env python3
"""Create controls for the direct Galileo Luna evaluator demo.

Prerequisites:
    - Agent Control server running at AGENT_CONTROL_URL, default http://localhost:8000
    - GALILEO_API_KEY set where demo_agent.py will run
    - Optional GALILEO_PROJECT_ID for project-scoped scorer resolution

Usage:
    uv run python setup_controls.py
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from agent_control import Agent, AgentControlClient, agents, controls

AGENT_NAME = "galileo-luna-agent"
AGENT_DESCRIPTION = "Demo agent protected by direct Galileo Luna scorer controls"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

LUNA_METRIC = os.getenv("GALILEO_LUNA_METRIC", "toxicity")
LUNA_THRESHOLD = float(os.getenv("GALILEO_LUNA_THRESHOLD", "0.5"))
GALILEO_PROJECT_ID = os.getenv("GALILEO_PROJECT_ID")

DEMO_STEPS = [
    {
        "type": "llm",
        "name": "draft_customer_reply",
        "description": "Draft customer-facing support replies.",
        "input_schema": {"message": {"type": "string"}},
        "output_schema": {"reply": {"type": "string"}},
    }
]


def luna_config() -> dict[str, Any]:
    """Build the direct Luna evaluator config used by the composite control."""
    config: dict[str, Any] = {
        "metric": LUNA_METRIC,
        "threshold": LUNA_THRESHOLD,
        "operator": "gte",
        "payload_field": "output",
        "on_error": "allow",
    }
    if GALILEO_PROJECT_ID:
        config["project_id"] = GALILEO_PROJECT_ID
    return config


DEMO_CONTROLS: list[dict[str, Any]] = [
    {
        "name": "luna-toxic-escalation-output",
        "definition": {
            "description": (
                "For risky customer messages, score the drafted reply with direct "
                "Galileo Luna and block when the local threshold matches."
            ),
            "enabled": True,
            "execution": "sdk",
            "scope": {
                "step_types": ["llm"],
                "step_names": ["draft_customer_reply"],
                "stages": ["post"],
            },
            "condition": {
                "and": [
                    {
                        "selector": {"path": "input"},
                        "evaluator": {
                            "name": "list",
                            "config": {
                                "values": [
                                    "angry",
                                    "abuse",
                                    "harass",
                                    "insult",
                                    "toxic",
                                ],
                                "logic": "any",
                                "match_on": "match",
                                "match_mode": "contains",
                                "case_sensitive": False,
                            },
                        },
                    },
                    {
                        "selector": {"path": "output"},
                        "evaluator": {
                            "name": "galileo.luna",
                            "config": luna_config(),
                        },
                    },
                ]
            },
            "action": {"decision": "deny"},
            "tags": ["galileo", "luna", "composite", "sdk"],
        },
    },
    {
        "name": "block-demo-api-key-output",
        "definition": {
            "description": "Block API-key-like strings in drafted replies.",
            "enabled": True,
            "execution": "sdk",
            "scope": {
                "step_types": ["llm"],
                "step_names": ["draft_customer_reply"],
                "stages": ["post"],
            },
            "condition": {
                "selector": {"path": "output"},
                "evaluator": {
                    "name": "regex",
                    "config": {"pattern": r"\bsk-[A-Za-z0-9_-]{12,}\b"},
                },
            },
            "action": {"decision": "deny"},
            "tags": ["regex", "secret", "sdk"],
        },
    },
]


async def create_or_get_control(
    client: AgentControlClient,
    *,
    name: str,
    definition: dict[str, Any],
) -> int:
    """Create a control, or update and reuse an existing control with the same name."""
    try:
        result = await controls.create_control(client, name=name, data=definition)
        control_id = int(result["control_id"])
        print(f"Created control: {name} ({control_id})")
        return control_id
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise

    page = await controls.list_controls(client, name=name, limit=100)
    for summary in page.get("controls", []):
        if summary.get("name") == name:
            control_id = int(summary["id"])
            await controls.set_control_data(client, control_id, definition)
            print(f"Updated existing control: {name} ({control_id})")
            return control_id

    raise RuntimeError(f"Control {name!r} already exists but could not be found")


async def setup_demo() -> None:
    """Register the demo agent, create controls, and attach them to the agent."""
    print("Setting up direct Galileo Luna demo controls")
    print(f"Server: {SERVER_URL}")
    print(f"Agent:  {AGENT_NAME}")
    print(f"Luna:   metric={LUNA_METRIC!r}, threshold={LUNA_THRESHOLD}")
    if GALILEO_PROJECT_ID:
        print(f"Project ID: {GALILEO_PROJECT_ID}")

    async with AgentControlClient(base_url=SERVER_URL, timeout=30.0) as client:
        await client.health_check()

        result = await agents.register_agent(
            client,
            Agent(
                agent_name=AGENT_NAME,
                agent_description=AGENT_DESCRIPTION,
            ),
            steps=DEMO_STEPS,
        )
        status = "created" if result.get("created") else "updated"
        print(f"Agent {status}")

        for spec in DEMO_CONTROLS:
            control_id = await create_or_get_control(
                client,
                name=str(spec["name"]),
                definition=spec["definition"],
            )
            await agents.add_agent_control(client, AGENT_NAME, control_id)
            print(f"Attached control {control_id} to {AGENT_NAME}")

    print()
    print("Setup complete. Run: uv run python demo_agent.py")


def main() -> None:
    """Run setup."""
    asyncio.run(setup_demo())


if __name__ == "__main__":
    main()
