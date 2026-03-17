"""Seed demo controls via the Agent Control SDK.

Usage:
    python seed_controls.py

Creates 4 step-specific controls:
  1. block-prompt-injection    - llm_call pre   (security)
  2. block-internal-data       - get_order_internal post (data protection)
  3. block-customer-pii        - lookup_customer_pii post (data protection)
  4. block-competitor-discuss   - llm_call pre   (business policy)

Controls are created DISABLED by default so the demo can start unprotected.
"""

import asyncio

import httpx

import agent_control

from settings import settings

CONTROLS = [
    {
        "name": "block-prompt-injection",
        "data": {
            "enabled": False,
            "execution": "server",
            "scope": {
                "stages": ["pre"],
                "step_names": ["llm_call"],
            },
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(?i)(ignore previous instructions|system prompt|you are now|forget everything|disregard all)"
                },
            },
            "action": {"decision": "deny"},
        },
    },
    {
        "name": "block-internal-data",
        "data": {
            "enabled": False,
            "execution": "server",
            "scope": {
                "stages": ["post"],
                "step_names": ["get_order_internal"],
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(?i)(internal_notes|cost_of_goods|profit_margin|escalation risk|friendly fraud)"
                },
            },
            "action": {"decision": "deny"},
        },
    },
    {
        "name": "block-customer-pii",
        "data": {
            "enabled": False,
            "execution": "server",
            "scope": {
                "stages": ["post"],
                "step_names": ["lookup_customer_pii"],
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(?i)(date_of_birth|billing_address|credit_card_on_file|internal_risk_score|agent_notes)"
                },
            },
            "action": {"decision": "deny"},
        },
    },
    {
        "name": "block-competitor-discuss",
        "data": {
            "enabled": False,
            "execution": "server",
            "scope": {
                "stages": ["pre"],
                "step_names": ["llm_call"],
            },
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(?i)(compare.*(amazon|shopify)|switch to (amazon|shopify)|better than (amazon|shopify))"
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
                # Already exists - look it up
                result = await agent_control.list_controls(
                    server_url=server_url, api_key=api_key
                )
                controls_list = result.get("controls", []) if isinstance(result, dict) else result
                ctrl_id = next(
                    c.get("id") for c in controls_list
                    if c.get("name") == ctrl_def["name"]
                )
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
