#!/usr/bin/env python3
"""
Setup script for Interactive Support Demo controls.

Creates 4 controls demonstrating AgentControl safety checks:
- LLM Controls: Block PII in input/output
- Tool Controls: Validate order IDs and prevent SQL injection

Usage:
    python examples/strands_integration/interactive_demo/setup_interactive_controls.py
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../sdks/python/src"))

from agent_control import Agent, AgentControlClient, agents, controls, policies


AGENT_NAME = "interactive-support-demo"
AGENT_ID = "550e8400-e29b-41d4-a716-446655440099"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

INTERACTIVE_CONTROLS = [
    # LLM Controls - Apply to all model interactions
    {
        "name": "block-pii-input",
        "description": "Block PII in user input (SSN, credit cards, emails)",
        "definition": {
            "description": "Block PII patterns in user messages",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                }
            },
            "action": {"decision": "deny", "message": "PII detected in user input"},
            "tags": ["pii", "demo"]
        }
    },
    {
        "name": "block-pii-output",
        "description": "Block PII in agent responses (SSN, credit cards, emails)",
        "definition": {
            "description": "Block PII patterns in agent outputs",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["post"]},
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                }
            },
            "action": {"decision": "deny", "message": "PII detected in agent response"},
            "tags": ["pii", "demo"]
        }
    },

    # Tool-Specific Controls - Target specific tools by name
    {
        "name": "validate-order-id-format",
        "description": "Validate order ID format for lookup_order tool",
        "definition": {
            "description": "Ensure order IDs follow ORD-XXXXX format",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["lookup_order"],
                "stages": ["pre"]
            },
            "selector": {"path": "input.order_id"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": r"ORD-.*[A-Za-z]"}  # Detects letters after hyphen (invalid)
            },
            "action": {
                "decision": "deny",
                "message": "Invalid order ID format. Expected: ORD-XXXXX"
            },
            "tags": ["validation", "demo"]
        }
    },
    {
        "name": "prevent-sql-injection-kb-query",
        "description": "Prevent SQL injection in knowledge base queries",
        "definition": {
            "description": "Block SQL injection patterns in search queries",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["search_knowledge_base"],
                "stages": ["pre"]
            },
            "selector": {"path": "input.query"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(\bSELECT\b|\bDROP\b|\bUNION\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|--|;|'|\"|\/\*|\*\/)"
                }
            },
            "action": {"decision": "deny", "message": "Invalid characters in query"},
            "tags": ["security", "demo"]
        }
    }
]


async def create_agent(client: AgentControlClient) -> str:
    """Create the interactive support demo agent."""
    print(f"\n✓ Creating agent: {AGENT_NAME}")
    agent_uuid = UUID(AGENT_ID)

    agent = Agent(
        agent_id=agent_uuid,
        agent_name=AGENT_NAME,
        agent_description="Interactive demo with real-time safety"
    )

    try:
        await agents.register_agent(client, agent, steps=[])
        print(f"  Agent UUID: {agent_uuid}")
        return str(agent_uuid)
    except Exception:
        print(f"  Agent already exists")
        return str(agent_uuid)


async def create_control_with_retry(
    client: AgentControlClient,
    name: str,
    control_definition: dict
) -> int:
    """Create or update a control."""
    try:
        result = await controls.create_control(client, name=name, data=control_definition)
        return result["control_id"]
    except Exception as e:
        if "409" in str(e):
            controls_list = await controls.list_controls(client, name=name, limit=1)
            if controls_list["controls"]:
                control_id = controls_list["controls"][0]["id"]
                await controls.set_control_data(client, control_id, control_definition)
                return control_id
        raise


async def create_interactive_controls(client: AgentControlClient) -> list[int]:
    """Create all interactive demo controls."""
    print(f"\n✓ Creating {len(INTERACTIVE_CONTROLS)} controls")
    control_ids = []

    for control_spec in INTERACTIVE_CONTROLS:
        name = control_spec["name"]
        definition = control_spec["definition"]
        control_id = await create_control_with_retry(client, name, definition)
        control_ids.append(control_id)
        print(f"  • {name} (ID: {control_id})")

    return control_ids


async def create_policy_with_retry(client: AgentControlClient, name: str) -> int:
    """Create or find existing policy."""
    print(f"\n✓ Creating policy: {name}")
    try:
        result = await policies.create_policy(client, name=name)
        return result["policy_id"]
    except Exception as e:
        if "409" in str(e):
            for policy_id in range(1, 20):
                try:
                    await policies.list_policy_controls(client, policy_id)
                    print(f"  Using existing policy (ID: {policy_id})")
                    return policy_id
                except Exception:
                    continue
            return 4
        raise


async def add_controls_to_policy(
    client: AgentControlClient,
    policy_id: int,
    control_ids: list[int]
) -> bool:
    """Add controls to a policy."""
    for control_id in control_ids:
        try:
            await policies.add_control_to_policy(client, policy_id, control_id)
        except Exception:
            pass  # Control may already be in policy
    print(f"  Added {len(control_ids)} controls to policy")
    return True


async def assign_policy(
    client: AgentControlClient,
    agent_uuid: str,
    policy_id: int
) -> bool:
    """Assign a policy to an agent."""
    print(f"\n✓ Assigning policy to agent")
    try:
        await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
        return True
    except Exception:
        return False


async def main():
    """Run the interactive demo control setup."""
    print("\n" + "=" * 50)
    print("AgentControl Setup - Interactive Demo")
    print("=" * 50)

    async with AgentControlClient(base_url=SERVER_URL) as client:
        try:
            await client.health_check()
            print("✓ Server connected")
        except Exception:
            print("✗ Server not available")
            print("  Start server: cd server && make run")
            return

        try:
            agent_uuid = await create_agent(client)
            control_ids = await create_interactive_controls(client)
            policy_id = await create_policy_with_retry(client, "interactive-demo-policy")
            await add_controls_to_policy(client, policy_id, control_ids)
            await assign_policy(client, agent_uuid, policy_id)

            print("\n" + "=" * 50)
            print("Setup Complete!")
            print("=" * 50)
            print(f"""
✅ Ready to run demo

Controls created:
  • block-pii-input (LLM, pre-stage)
  • block-pii-output (LLM, post-stage)
  • validate-order-id-format (Tool: lookup_order)
  • prevent-sql-injection-kb-query (Tool: search_knowledge_base)

Run the demo:
  streamlit run examples/strands_integration/interactive_demo/interactive_support_demo.py
""")

        except Exception as e:
            print(f"\n❌ Setup failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
