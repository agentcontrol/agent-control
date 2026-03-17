"""Seed demo controls via the Agent Control SDK.

Usage:
    python seed_controls.py

Creates 4 controls:
  1. block-prompt-injection    - llm_call pre    (security)
  2. block-internal-data       - get_order_internal post (data protection)
  3. block-pii                 - lookup_customer_pii + llm_call post (PII/SSN)
  4. block-competitor-discuss   - llm_call pre    (business policy)

Controls are created DISABLED by default so the demo can start unprotected.
"""

import asyncio

from dotenv import load_dotenv
load_dotenv()

import httpx

import agent_control

from settings import settings

CONTROLS = [
    {
        "name": "block-prompt-injection",
        "data": {
            "enabled": False,
            "execution": "sdk",
            "scope": {
                "stages": ["pre"],
                "step_types": ["llm"],
                "step_names": ["llm_call"],
            },
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"([Ii]gnore previous instructions|[Ss]ystem prompt|[Yy]ou are now|[Ff]orget everything|[Dd]isregard all)"
                },
            },
            "action": {"decision": "deny"},
        },
    },
    {
        "name": "block-internal-data",
        "data": {
            "enabled": False,
            "execution": "sdk",
            "scope": {
                "stages": ["post"],
                "step_types": ["tool"],
                "step_names": ["get_order_internal"],
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(internal_notes|cost_of_goods|profit_margin|[Ee]scalation risk|[Ff]riendly fraud)"
                },
            },
            "action": {"decision": "deny"},
        },
    },
    {
        "name": "block-pii",
        "data": {
            "enabled": False,
            "execution": "sdk",
            "scope": {
                "stages": ["post"],
                "step_names": ["lookup_customer_pii", "llm_call"],
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\d{3}-\d{2}-\d{4}"
                },
            },
            "action": {"decision": "deny"},
        },
    },
    {
        "name": "block-competitor-discuss",
        "data": {
            "enabled": False,
            "execution": "sdk",
            "scope": {
                "stages": ["pre"],
                "step_types": ["llm"],
                "step_names": ["llm_call"],
            },
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"([Cc]ompare.*([Aa]mazon|[Ss]hopify)|[Ss]witch to ([Aa]mazon|[Ss]hopify)|[Bb]etter than ([Aa]mazon|[Ss]hopify))"
                },
            },
            "action": {"decision": "deny"},
        },
    },
]


async def seed() -> None:
    server_url = settings.agent_control_url
    api_key = settings.agent_control_api_key or None

    # Register agent via init (also starts the SDK)
    agent_control.init(
        agent_name=settings.agent_name,
        agent_description="Customer support agent with Agent Control runtime guardrails",
        server_url=server_url,
        api_key=api_key,
        policy_refresh_interval_seconds=0,
    )
    print(f"Registered agent: {settings.agent_name}")

    for ctrl_def in CONTROLS:
        try:
            ctrl = await agent_control.create_control(
                name=ctrl_def["name"],
                data=ctrl_def["data"],
                server_url=server_url,
                api_key=api_key,
            )
            ctrl_id = ctrl.get("control_id") or ctrl.get("id")
            print(f"Created control: {ctrl_def['name']} (id={ctrl_id})")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                # Already exists - look it up by name
                result = await agent_control.list_controls(
                    server_url=server_url,
                    api_key=api_key,
                    name=ctrl_def["name"],
                )
                controls_list = result.get("controls", []) if isinstance(result, dict) else result
                ctrl_id = next(
                    (c.get("id") for c in controls_list
                     if c.get("name") == ctrl_def["name"]),
                    None,
                )
                if ctrl_id is None:
                    raise RuntimeError(
                        f"Control '{ctrl_def['name']}' returned 409 but was not found via list_controls"
                    ) from e
                print(f"Control already exists: {ctrl_def['name']} (id={ctrl_id})")
            else:
                raise

        await agent_control.add_agent_control(
            agent_name=settings.agent_name,
            control_id=ctrl_id,
            server_url=server_url,
            api_key=api_key,
        )

    print("Controls attached to agent. Done!")
    await agent_control.ashutdown()


if __name__ == "__main__":
    asyncio.run(seed())
