#!/usr/bin/env python3
"""
Setup script for Interactive Support Demo controls.

Creates 4 controls demonstrating AgentControl safety checks:
- User Input: Block PII and SQL injection patterns
- Agent Output: Block PII in responses
- Universal Tool Protection: Block PII in ALL tool inputs (step_types=["tool"])

Demonstrates different scoping patterns:
  • step_names=[...] - Target specific callbacks
  • step_types=["tool"] - Target ALL tool calls

Usage:
    python examples/strands_integration/interactive_demo/setup_interactive_controls.py
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../sdks/python/src"))

from agent_control import Agent, AgentControlClient, agents, controls


AGENT_NAME = "interactive-support-demo"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

INTERACTIVE_CONTROLS = [
    # User Input Controls - Block unsafe patterns in user messages
    {
        "name": "block-pii-input",
        "description": "Block PII in user input (SSN, credit cards, emails)",
        "definition": {
            "description": "Block PII patterns in user messages",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_names": ["check_before_invocation", "check_before_model"],
                "stages": ["pre"]
            },
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                }
            },
            "action": {"decision": "deny", "message": "PII detected in user input"},
            "tags": ["pii", "security"]
        }
    },
    {
        "name": "prevent-sql-injection-user-input",
        "description": "Prevent SQL injection patterns in user messages",
        "definition": {
            "description": "Block SQL injection patterns before LLM processes",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_names": ["check_before_invocation", "check_before_model"],
                "stages": ["pre"]
            },
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(\bDROP\s+TABLE\b|\bDROP\s+DATABASE\b|--;)"
                }
            },
            "action": {"decision": "deny", "message": "Potentially malicious SQL patterns detected"},
            "tags": ["security"]
        }
    },

    # Agent Output Controls - Block unsafe patterns in agent responses
    {
        "name": "block-pii-output",
        "description": "Block PII in agent responses (SSN, credit cards, emails)",
        "definition": {
            "description": "Block PII patterns in agent outputs",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_names": ["check_after_model"],
                "stages": ["post"]
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                }
            },
            "action": {"decision": "deny", "message": "PII detected in agent response"},
            "tags": ["pii", "security"]
        }
    },

    # Universal Tool Control - Applies to ALL tool calls
    {
        "name": "block-pii-all-tool-inputs",
        "description": "Block PII in any tool input (universal tool protection)",
        "definition": {
            "description": "Prevent PII from being passed to any tool (lookup_order, search_knowledge_base, check_return_policy)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],  # Applies to ALL tools
                "stages": ["pre"]
            },
            "selector": {"path": "input"},  # Check entire tool input
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"
                }
            },
            "action": {"decision": "deny", "message": "PII not allowed in tool inputs"},
            "tags": ["pii", "security", "tools"]
        }
    }
]


async def create_agent(client: AgentControlClient) -> str:
    """Create the interactive support demo agent."""
    print(f"\n✓ Creating agent: {AGENT_NAME}")

    agent = Agent(
        agent_name=AGENT_NAME,
        agent_description="Interactive demo with real-time safety"
    )

    try:
        await agents.register_agent(client, agent, steps=[])
        print(f"  Agent: {AGENT_NAME}")
        return AGENT_NAME
    except Exception:
        print(f"  Agent already exists")
        return AGENT_NAME


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


async def attach_controls_to_agent(
    client: AgentControlClient,
    agent_name: str,
    control_ids: list[int],
) -> None:
    """Attach controls directly to the agent."""
    print(f"\n✓ Attaching {len(control_ids)} controls to agent")
    for control_id in control_ids:
        try:
            await agents.add_agent_control(client, agent_name, control_id)
        except Exception:
            pass


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
            agent_name = await create_agent(client)
            control_ids = await create_interactive_controls(client)
            await attach_controls_to_agent(client, agent_name, control_ids)

            print("\n" + "=" * 50)
            print("Setup Complete!")
            print("=" * 50)
            print(f"""
✅ Ready to run demo

Controls created:
  • block-pii-input (Scope: user input - check_before_invocation, check_before_model)
  # • prevent-sql-injection-user-input (Scope: user input - check_before_invocation, check_before_model)
  • block-pii-output (Scope: agent output - check_after_model)
  • block-pii-all-tool-inputs (Scope: ALL tools - step_types=["tool"])

Test cases:
  ✓ "My SSN is 123-45-6789" → Blocked by block-pii-input
  # ✓ "DROP TABLE orders--" → Blocked by prevent-sql-injection-user-input
  ✓ Tool call with PII → Blocked by block-pii-all-tool-inputs (universal)

Run the demo:
  streamlit run examples/strands_integration/interactive_demo/interactive_support_demo.py
""")

        except Exception as e:
            print(f"\n❌ Setup failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
