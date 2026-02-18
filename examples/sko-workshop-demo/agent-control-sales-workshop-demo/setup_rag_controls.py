#!/usr/bin/env python3
"""Create RAG-specific controls and attach to the RAG demo agent."""

import asyncio
import os
import sys
from uuid import UUID

SDK_FALLBACK = "/Users/namrataghadi/code/agentcontrol/agent-control/sdks/python/src"
if SDK_FALLBACK not in sys.path:
    sys.path.insert(0, SDK_FALLBACK)

from agent_control import Agent, AgentControlClient, agents, controls, policies

AGENT_NAME = "RAG Q&A Agent"
AGENT_ID = "9e9a1c8e-8c3f-4c6d-9d2a-0d3d5e8a1b77"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
POLICY_NAME = "rag-demo-policy"

CONTROLS = [
    {
        "name": "rag-block-prompt-injection",
        "definition": {
            "description": "Block prompt injection attempts in user input",
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
    {
        "name": "rag-block-pii-output",
        "definition": {
            "description": "Block PII in final answer",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["post"]},
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
            },
            "action": {"decision": "deny"},
            "tags": ["pii"],
        },
    },
    {
        "name": "rag-block-pii-in-retrieval",
        "definition": {
            "description": "Block PII in retrieval queries",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {"path": "input.query"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
            },
            "action": {"decision": "deny"},
            "tags": ["pii"],
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
    print("AgentControl RAG Demo - Setup Controls")
    print("=" * 70)
    print(f"Server: {SERVER_URL}")

    async with AgentControlClient(base_url=SERVER_URL) as client:
        try:
            await client.health_check()
            print("✓ Server healthy")
        except Exception as e:
            print(f"✗ Server not reachable: {e}")
            print("Start server: cd server && make run")
            return

        agent = Agent(
            agent_id=UUID(AGENT_ID),
            agent_name=AGENT_NAME,
            agent_description="RAG Q&A demo agent",
        )
        await agents.register_agent(client, agent, steps=[])
        print(f"✓ Agent registered: {AGENT_NAME}")

        # Create or reuse policy
        policy_id = None
        try:
            result = await policies.create_policy(client, POLICY_NAME)
            policy_id = result["policy_id"]
            print(f"✓ Policy created: {POLICY_NAME} (ID {policy_id})")
        except Exception as e:
            if "409" in str(e):
                try:
                    policy_info = await agents.get_agent_policy(client, AGENT_ID)
                    policy_id = policy_info.get("policy_id")
                    print(f"✓ Using existing policy ID: {policy_id}")
                except Exception:
                    import time
                    alt_name = f"{POLICY_NAME}-{int(time.time())}"
                    result = await policies.create_policy(client, alt_name)
                    policy_id = result["policy_id"]
                    print(f"✓ Policy created: {alt_name} (ID {policy_id})")
            else:
                raise

        await policies.assign_policy_to_agent(client, AGENT_ID, policy_id)
        print("✓ Policy assigned to agent")

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

        print("\nSetup complete. Start the RAG app or CLI demo.")


if __name__ == "__main__":
    asyncio.run(main())
