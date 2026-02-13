#!/usr/bin/env python3
"""
Setup script for Interactive Support Demo controls.

This script creates controls specifically for the interactive customer support demo,
focusing on controls that demonstrate real-time protection visually.

Controls created:
1. block-pii-input - Blocks SSN, credit cards, emails in user input (regex)
2. block-pii-output - Blocks SSN, credit cards, emails in agent output (regex)

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


# Configuration
AGENT_NAME = "interactive-support-demo"
AGENT_ID = "550e8400-e29b-41d4-a716-446655440099"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


# Interactive demo controls (optimized for visual demonstration)
INTERACTIVE_CONTROLS = [
    {
        "name": "block-pii-input",
        "description": "CRITICAL: Block PII in user input (SSN, credit cards, emails)",
        "definition": {
            "description": "Block PII patterns in user messages to prevent data exposure",
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
                "message": "PII detected in user input"
            },
            "tags": ["pii", "support", "critical", "demo", "pre-check"]
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
            "tags": ["pii", "support", "critical", "demo", "post-check"]
        }
    }
]


async def create_agent(client: AgentControlClient) -> str:
    """Create the interactive support demo agent."""
    print("\n" + "=" * 70)
    print("STEP 1: Creating Interactive Support Demo Agent")
    print("=" * 70)

    agent_uuid = UUID(AGENT_ID)

    agent = Agent(
        agent_id=agent_uuid,
        agent_name=AGENT_NAME,
        agent_description="Interactive customer support demo with real-time AgentControl protection"
    )

    try:
        await agents.register_agent(client, agent, steps=[])
        print(f"✓ Agent registered: {AGENT_NAME}")
        print(f"  Agent UUID: {agent_uuid}")
        print(f"  Purpose: Interactive demo with visual safety feedback")
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


async def create_interactive_controls(client: AgentControlClient) -> list[int]:
    """Create all interactive demo controls."""
    print("\n" + "=" * 70)
    print("STEP 2: Creating Interactive Demo Controls")
    print("=" * 70)

    control_ids = []

    for control_spec in INTERACTIVE_CONTROLS:
        name = control_spec["name"]
        description = control_spec["description"]
        definition = control_spec["definition"]

        print(f"\n📋 Creating control: {name}")
        print(f"   {description}")
        print(f"   Type: {definition['evaluator']['name']}")

        evaluator_config = definition['evaluator']['config']
        if 'pattern' in evaluator_config:
            # Count number of patterns in the combined OR expression
            pattern_count = evaluator_config['pattern'].count('|') + 1
            print(f"   Pattern: Combined PII regex ({pattern_count} patterns)")

        print(f"   Action: {definition['action']['decision']}")

        control_id = await create_control_with_retry(client, name, definition)
        control_ids.append(control_id)
        print(f"   ✓ Control created with ID: {control_id}")

    print(f"\n✓ Created {len(control_ids)} interactive demo control(s)")
    return control_ids


async def create_policy_with_retry(client: AgentControlClient, name: str) -> int:
    """Create a policy, handling existing policies."""
    print("\n" + "=" * 70)
    print("STEP 3: Creating Interactive Demo Policy")
    print("=" * 70)

    try:
        result = await policies.create_policy(client, name=name)
        policy_id = result["policy_id"]
        print(f"✓ Created policy '{name}' with ID: {policy_id}")
        return policy_id
    except Exception as e:
        if "409" in str(e):
            # Policy already exists - try to find it by checking policy IDs
            print(f"  ℹ️  Policy '{name}' already exists, looking up ID...")
            # TODO: Add list_policies() function to SDK for proper lookup
            # For now, try to find the policy by checking which IDs exist
            for policy_id in range(1, 20):
                try:
                    # Try to list controls for this policy - if it works, policy exists
                    await policies.list_policy_controls(client, policy_id)
                    print(f"  ℹ️  Using existing policy (ID: {policy_id})")
                    return policy_id
                except Exception:
                    continue
            # If we couldn't find it, return a default
            print(f"  ⚠️  Could not determine policy ID, using default ID 4")
            return 4
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
    """Run the interactive demo control setup."""
    print("\n" + "=" * 70)
    print("INTERACTIVE SUPPORT DEMO - CONTROL SETUP")
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

            # 2. Create controls
            control_ids = await create_interactive_controls(client)

            # 3. Create policy
            policy_name = "interactive-demo-policy"
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
✅ Interactive Support Demo Ready

Controls Active:
  1. block-pii-input
     → Blocks SSN, credit cards, emails in user input (regex)

  2. block-pii-output
     → Blocks SSN, credit cards, emails in agent output (regex)

Next Steps:
  Run the interactive demo:
    streamlit run examples/strands_integration/interactive_demo/interactive_support_demo.py

  Try attack prompts in the app to see AgentControl block them in real-time!

Value Demonstrated:
  ✓ Real-time PII protection (regex evaluator)
  ✓ Pre-stage and post-stage checking
  ✓ Live safety dashboard
  ✓ Complete audit trail
""")

        except Exception as e:
            print(f"\n\n❌ Setup failed: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
