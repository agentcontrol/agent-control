#!/usr/bin/env python3
"""
Setup script for Layered Governance Demo controls.

This script creates AgentControl safety controls for the steering demo.
Steering (quality layer) is implemented in code and doesn't need server setup.

Controls created:
1. block-pii-output - Blocks SSN, credit cards, emails in agent output (regex)

Usage:
    python setup_steering_controls.py
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


# Configuration
AGENT_NAME = "steering-demo"
AGENT_ID = "550e8400-e29b-41d4-a716-446655440010"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


# Safety controls for the demo
SAFETY_CONTROLS = [
    {
        "name": "block-pii-input",
        "description": "CRITICAL: Block PII in user input (SSN, credit cards, emails)",
        "definition": {
            "description": "Block PII patterns in user messages to prevent sensitive data processing",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["llm"],
                "stages": ["pre"]  # Check user input
            },
            "selector": {"path": "input"},  # Check input field
            "evaluator": {
                "name": "regex",
                "config": {
                    # Combined PII pattern (SSN, credit card, email)
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                }
            },
            "action": {
                "decision": "deny",
                "message": "PII detected in user input - cannot process"
            },
            "tags": ["pii", "safety", "critical", "demo", "input"]
        }
    },
    {
        "name": "block-pii-output",
        "description": "CRITICAL: Block PII in agent responses (SSN, credit cards, emails)",
        "definition": {
            "description": "Block PII patterns in agent outputs to prevent data leaks",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["llm"],
                "stages": ["post"]  # Check agent output
            },
            "selector": {"path": "output"},  # Check output field
            "evaluator": {
                "name": "regex",
                "config": {
                    # Combined PII pattern (SSN, credit card, email)
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                }
            },
            "action": {
                "decision": "deny",
                "message": "PII detected - regenerating safe response"
            },
            "tags": ["pii", "safety", "critical", "demo", "output"]
        }
    }
]


async def create_agent(client: AgentControlClient) -> str:
    """Create the steering demo agent."""
    print("\n" + "=" * 70)
    print("STEP 1: Creating Steering Demo Agent")
    print("=" * 70)

    agent_uuid = UUID(AGENT_ID)

    agent = Agent(
        agent_id=agent_uuid,
        agent_name=AGENT_NAME,
        agent_description="Layered governance demo with AgentControl + Strands Steering"
    )

    try:
        await agents.register_agent(client, agent, steps=[])
        print(f"✓ Agent registered: {AGENT_NAME}")
        print(f"  Agent UUID: {agent_uuid}")
        print(f"  Purpose: Demonstrate layered governance (safety + quality)")
        return str(agent_uuid)

    except Exception as e:
        print(f"ℹ️  Agent might already exist: {e}")
        return str(agent_uuid)


async def create_control_with_retry(
    client: AgentControlClient,
    name: str,
    control_definition: dict
) -> int:
    """Create a control with the given definition, handling existing controls."""
    try:
        result = await controls.create_control(client, name=name, data=control_definition)
        return result["control_id"]
    except Exception as e:
        # If control already exists, look it up and return its ID
        if "409" in str(e):
            print(f"  ℹ️  Control '{name}' already exists, looking it up...")
            controls_list = await controls.list_controls(client, name=name, limit=1)
            if controls_list["controls"]:
                control_id = controls_list["controls"][0]["id"]
                # Update with new definition
                await controls.set_control_data(client, control_id, control_definition)
                print(f"  ℹ️  Updated existing control (ID: {control_id})")
                return control_id
            else:
                print(f"❌ Could not find existing control '{name}'")
                raise
        else:
            print(f"✗ Failed to create control '{name}': {e}")
            raise


async def create_safety_controls(client: AgentControlClient) -> list[int]:
    """Create safety controls."""
    print("\n" + "=" * 70)
    print("STEP 2: Creating Safety Controls (AgentControl Layer)")
    print("=" * 70)

    control_ids = []

    for control_spec in SAFETY_CONTROLS:
        name = control_spec["name"]
        description = control_spec["description"]
        definition = control_spec["definition"]

        print(f"\n📋 Creating control: {name}")
        print(f"   {description}")
        print(f"   Type: {definition['evaluator']['name']}")
        print(f"   Action: {definition['action']['decision']}")

        control_id = await create_control_with_retry(client, name, definition)
        control_ids.append(control_id)
        print(f"   ✓ Control created with ID: {control_id}")

    print(f"\n✓ Created {len(control_ids)} safety control(s)")
    return control_ids


async def create_policy_with_retry(client: AgentControlClient, name: str) -> int:
    """Create a policy, handling existing policies."""
    print("\n" + "=" * 70)
    print("STEP 3: Creating Policy")
    print("=" * 70)

    try:
        result = await policies.create_policy(client, name=name)
        policy_id = result["policy_id"]
        print(f"✓ Created policy '{name}' with ID: {policy_id}")
        return policy_id
    except Exception as e:
        if "409" in str(e):
            print(f"  ℹ️  Policy '{name}' already exists, looking up ID...")
            for policy_id in range(1, 20):
                try:
                    await policies.list_policy_controls(client, policy_id)
                    print(f"  ℹ️  Using existing policy (ID: {policy_id})")
                    return policy_id
                except Exception:
                    continue
            print(f"  ⚠️  Could not determine policy ID, using default ID 5")
            return 5
        print(f"✗ Failed to create policy: {e}")
        raise


async def add_controls_to_policy(
    client: AgentControlClient,
    policy_id: int,
    control_ids: list[int]
) -> bool:
    """Add controls to a policy."""
    print("\n  Adding controls to policy...")

    success_count = 0
    for control_id in control_ids:
        try:
            await policies.add_control_to_policy(client, policy_id, control_id)
            print(f"  ✓ Added control {control_id} to policy {policy_id}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ Failed to add control {control_id} to policy: {e}")

    print(f"\n✓ Added {success_count}/{len(control_ids)} controls to policy")
    return success_count == len(control_ids)


async def assign_policy(
    client: AgentControlClient,
    agent_uuid: str,
    policy_id: int
) -> bool:
    """Assign a policy to an agent."""
    print("\n" + "=" * 70)
    print("STEP 4: Assigning Policy to Agent")
    print("=" * 70)

    try:
        await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
        print(f"✓ Assigned policy {policy_id} to agent {agent_uuid}")
        return True
    except Exception as e:
        print(f"✗ Failed to assign policy: {e}")
        return False


async def main():
    """Run the steering demo control setup."""
    print("\n" + "=" * 70)
    print("LAYERED GOVERNANCE DEMO - CONTROL SETUP")
    print("=" * 70)
    print(f"\nServer URL: {SERVER_URL}")
    print(f"Agent: {AGENT_NAME}")
    print(f"Agent ID: {AGENT_ID}")

    async with AgentControlClient(base_url=SERVER_URL) as client:
        # Check server health
        try:
            health = await client.health_check()
            print(f"\n✓ Server is healthy: {health.get('status', 'unknown')}")
        except Exception as e:
            print(f"\n✗ Server not available: {e}")
            print("\nMake sure the server is running:")
            print("  cd server && make run")
            return

        try:
            # 1. Create agent
            agent_uuid = await create_agent(client)

            # 2. Create safety controls
            control_ids = await create_safety_controls(client)

            # 3. Create policy
            policy_name = "steering-demo-policy"
            policy_id = await create_policy_with_retry(client, policy_name)

            # 4. Add controls to policy
            await add_controls_to_policy(client, policy_id, control_ids)

            # 5. Assign policy to agent
            await assign_policy(client, agent_uuid, policy_id)

            # Success summary
            print("\n" + "=" * 70)
            print("SETUP COMPLETE!")
            print("=" * 70)
            print(f"""
✅ Layered Governance Demo Ready

LAYER 1 - Safety (AgentControl):
  → block-pii-input: Blocks SSN, credit cards, emails in user input (regex, pre-stage)
  → block-pii-output: Blocks SSN, credit cards, emails in agent output (regex, post-stage)

LAYER 2 - Quality (Strands Steering):
  → Empathy guidance (code-based)
  → On-topic guidance (code-based)
  → Brevity guidance (code-based)

Next Steps:
  Run the demo:
    streamlit run layered_governance_demo.py

  Try both types of test prompts to see:
    🛡️ Safety Layer: Hard blocks for PII violations
    ✨ Quality Layer: Soft guidance for better responses

Value Demonstrated:
  ✓ Safety enforcement (AgentControl)
  ✓ Quality optimization (Steering)
  ✓ Layered governance approach
  ✓ Complete observability
""")

        except Exception as e:
            print(f"\n\n❌ Setup failed: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
