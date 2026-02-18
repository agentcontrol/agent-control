#!/usr/bin/env python3
"""
Create demo agent + policy + controls for the Sales Assist workshop.

This script is idempotent: it updates existing controls if they already exist.
"""

import asyncio
import os
import sys
from uuid import UUID

# SDK fallback path (monorepo checkout)
SDK_FALLBACK = "/Users/namrataghadi/code/agentcontrol/agent-control/sdks/python/src"
if SDK_FALLBACK not in sys.path:
    sys.path.insert(0, SDK_FALLBACK)

from agent_control import Agent, AgentControlClient, agents, controls, policies

AGENT_NAME = "Sales Assist Agent"
AGENT_ID = "b2b8d4d4-1b8a-4e3d-9a1d-2d9d924b9d42"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

CONTROLS = [
    # Block prompt injection in input (pre)
    {
        "name": "block-prompt-injection",
        "definition": {
            "description": "Block common prompt injection patterns",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(?i)(ignore.{0,20}instructions|system:|developer:|you are now|forget previous)"
                }
            },
            "action": {"decision": "deny"},
            "tags": ["security", "prompt-injection"],
        },
    },
    # Block PII in output (post)
    {
        "name": "block-ssn-output",
        "definition": {
            "description": "Block SSN leakage in LLM output",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["post"]},
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
            },
            "action": {"decision": "deny"},
            "tags": ["pii", "ssn"],
        },
    },
    # Enforce discount policy on tool call (pre)
    {
        "name": "block-excessive-discount",
        "definition": {
            "description": "Block quotes with discount > 30%",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {"path": "input.discount_pct"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Matches 31-99 or 100+ when discount_pct is a number
                    "pattern": r"^(3[1-9]|[4-9]\d|\d{3,})$"
                },
            },
            "action": {"decision": "deny"},
            "tags": ["policy", "pricing"],
        },
    },
    # Log all quotes for audit (pre)
    {
        "name": "log-quote-requests",
        "definition": {
            "description": "Log all quote tool calls for audit",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {"path": "*"},
            "evaluator": {"name": "regex", "config": {"pattern": r".*"}},
            "action": {"decision": "log"},
            "tags": ["audit"],
        },
    },
]


async def _create_or_update_control(client: AgentControlClient, name: str, definition: dict) -> int:
    try:
        result = await controls.create_control(client, name=name, data=definition)
        return result["control_id"]
    except Exception as e:
        if "409" in str(e):
            existing = await controls.list_controls(client, name=name, limit=1)
            ctrl = (existing.get("controls") or [None])[0]
            if not ctrl:
                raise
            control_id = ctrl["id"]
            await controls.set_control_data(client, control_id, definition)
            return control_id
        raise


async def main() -> None:
    print("=" * 70)
    print("AgentControl Sales Workshop - Setup")
    print("=" * 70)
    print(f"Server: {SERVER_URL}")

    async with AgentControlClient(base_url=SERVER_URL) as client:
        # Health check
        try:
            await client.health_check()
            print("✓ Server healthy")
        except Exception as e:
            print(f"✗ Server not reachable: {e}")
            print("Start server: cd server && make run")
            return

        # Create/Update agent
        agent = Agent(
            agent_id=UUID(AGENT_ID),
            agent_name=AGENT_NAME,
            agent_description="Sales assistant demo agent",
        )
        await agents.register_agent(client, agent, steps=[])
        print(f"✓ Agent registered: {AGENT_NAME}")

        # Create or find policy
        policy_name = "sales-workshop-policy"
        policy_id = None
        try:
            policy = await policies.create_policy(client, policy_name)
            policy_id = policy["policy_id"]
            print(f"✓ Policy created: {policy_name} (ID {policy_id})")
        except Exception as e:
            if "409" in str(e):
                # Try to resolve existing policy from agent
                try:
                    policy_info = await agents.get_agent_policy(client, AGENT_ID)
                    policy_id = policy_info.get("policy_id")
                    print(f"✓ Using existing policy ID: {policy_id}")
                except Exception:
                    # Fallback: create a unique policy
                    import time
                    policy_name = f"sales-workshop-policy-{int(time.time())}"
                    policy = await policies.create_policy(client, policy_name)
                    policy_id = policy["policy_id"]
                    print(f"✓ Policy created: {policy_name} (ID {policy_id})")
            else:
                raise

        # Assign policy to agent
        await policies.assign_policy_to_agent(client, AGENT_ID, policy_id)
        print(f"✓ Policy assigned to agent")

        # Create controls and add to policy
        control_ids = []
        for c in CONTROLS:
            control_id = await _create_or_update_control(client, c["name"], c["definition"])
            control_ids.append(control_id)
            try:
                await policies.add_control_to_policy(client, policy_id, control_id)
            except Exception:
                pass

        print("\nControls configured:")
        for c in CONTROLS:
            print(f"  • {c['name']}")

        print("\nSetup complete. Run: uv run python run_demo.py")


if __name__ == "__main__":
    asyncio.run(main())
