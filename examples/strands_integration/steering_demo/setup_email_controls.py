#!/usr/bin/env python3
"""
Setup AgentControl safety controls for email demo.

CRITICAL CONTROLS:
- Block PII in email body (SSN, credit cards, phone numbers)
- Block credentials/secrets in email body
- Block internal system information

These are HARD BLOCKS (deny action) - critical for compliance (GDPR, PCI-DSS).
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env", override=False)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../sdks/python/src"))

from agent_control import Agent, AgentControlClient, agents, controls, policies


# Configuration
AGENT_NAME = "banking-email-agent"
AGENT_ID = "550e8400-e29b-41d4-a716-446655440030"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


# CRITICAL SAFETY CONTROLS
SAFETY_CONTROLS = [
    # Control 1: Detect PII in LLM responses (check what agent plans to say/do)
    {
        "name": "detect-pii-in-responses",
        "description": "CRITICAL: Detect PII in agent responses (SSN, credit cards, phone)",
        "definition": {
            "description": "Prevent PII leakage by checking LLM output before actions (GDPR/PCI-DSS compliance)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["llm"],  # Check LLM responses
                "stages": ["post"]  # Check AFTER LLM generates response
            },
            "selector": {"path": "output"},  # Check LLM output text
            "evaluator": {
                "name": "regex",
                "config": {
                    # Match SSN (123-45-6789), Credit Card (4532-1234-5678-9010), Phone (555-123-4567)
                    "pattern": r"(\d{3}[-\s]?\d{2}[-\s]?\d{4})|(\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4})|(\d{3}[-\s]?\d{3}[-\s]?\d{4})"
                }
            },
            "action": {
                "decision": "warn",  # WARN (don't block LLM, let steering handle redaction)
                "message": "PII detected in response - steering will guide redaction"
            },
            "tags": ["pii", "gdpr", "pci-dss", "critical"]
        }
    },

    # Control 2: Detect credentials/API keys in LLM responses
    {
        "name": "detect-credentials-in-responses",
        "description": "CRITICAL: Detect credentials or API keys in agent responses",
        "definition": {
            "description": "Prevent credential leakage by checking LLM output",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["llm"],
                "stages": ["post"]
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Match patterns like: api_key, password, secret, token
                    "pattern": r"(api[_-]?key|password|secret|token|credential)[\s:=]+['\"]?[\w\-]{8,}"
                }
            },
            "action": {
                "decision": "warn",
                "message": "Credentials detected in response - steering will guide removal"
            },
            "tags": ["credentials", "secrets", "critical"]
        }
    },

    # Control 3: Detect internal system info in LLM responses
    {
        "name": "detect-internal-info-in-responses",
        "description": "Detect internal system information in agent responses",
        "definition": {
            "description": "Prevent exposure of internal database names, server IPs, etc.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["llm"],
                "stages": ["post"]
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Match database names, server paths
                    "pattern": r"(database|db|server|localhost|127\.0\.0\.1|/var/|/etc/|C:\\\\)"
                }
            },
            "action": {
                "decision": "warn",
                "message": "Internal system info detected in response - steering will guide removal"
            },
            "tags": ["internal-info", "security"]
        }
    }
]


async def create_agent(client: AgentControlClient) -> str:
    """Create the email safety demo agent."""
    print("\n" + "=" * 70)
    print("STEP 1: Creating Email Safety Demo Agent")
    print("=" * 70)

    agent_uuid = UUID(AGENT_ID)

    agent = Agent(
        agent_id=agent_uuid,
        agent_name=AGENT_NAME,
        agent_description="Email safety demo - prevents PII leakage in automated emails"
    )

    try:
        await agents.register_agent(client, agent, steps=[])
        print(f"✓ Agent registered: {AGENT_NAME}")
        print(f"  Agent UUID: {agent_uuid}")
        return str(agent_uuid)
    except Exception as e:
        print(f"ℹ️  Agent might already exist: {e}")
        return str(agent_uuid)


async def create_control_with_retry(
    client: AgentControlClient,
    name: str,
    control_definition: dict
) -> int:
    """Create a control with the given definition."""
    try:
        result = await controls.create_control(client, name=name, data=control_definition)
        return result["control_id"]
    except Exception as e:
        if "409" in str(e):
            print(f"  ℹ️  Control '{name}' already exists, looking it up...")
            controls_list = await controls.list_controls(client, name=name, limit=1)
            if controls_list["controls"]:
                control_id = controls_list["controls"][0]["id"]
                await controls.set_control_data(client, control_id, control_definition)
                print(f"  ℹ️  Updated existing control (ID: {control_id})")
                return control_id
        print(f"✗ Failed to create control '{name}': {e}")
        raise


async def create_safety_controls(client: AgentControlClient) -> list[int]:
    """Create critical safety controls."""
    print("\n" + "=" * 70)
    print("STEP 2: Creating CRITICAL Safety Controls")
    print("=" * 70)

    control_ids = []

    for control_spec in SAFETY_CONTROLS:
        name = control_spec["name"]
        description = control_spec["description"]
        definition = control_spec["definition"]

        print(f"\n🛡️ Creating CRITICAL control: {name}")
        print(f"   {description}")
        print(f"   Action: {definition['action']['decision']} (HARD BLOCK)")

        control_id = await create_control_with_retry(client, name, definition)
        control_ids.append(control_id)
        print(f"   ✓ Control created with ID: {control_id}")

    print(f"\n✓ Created {len(control_ids)} critical safety control(s)")
    return control_ids


async def create_policy_with_retry(client: AgentControlClient, name: str) -> int:
    """Create a policy."""
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
            print(f"  ℹ️  Policy '{name}' already exists, using existing...")
            # Try a few policy IDs
            for policy_id in range(1, 20):
                try:
                    await policies.list_policy_controls(client, policy_id)
                    print(f"  ℹ️  Using existing policy (ID: {policy_id})")
                    return policy_id
                except:
                    continue
            return 6  # Default fallback
        raise


async def add_controls_to_policy(
    client: AgentControlClient,
    policy_id: int,
    control_ids: list[int]
) -> bool:
    """Add controls to policy."""
    print("\n  Adding controls to policy...")

    for control_id in control_ids:
        try:
            await policies.add_control_to_policy(client, policy_id, control_id)
            print(f"  ✓ Added control {control_id} to policy {policy_id}")
        except Exception as e:
            print(f"  ✗ Failed to add control {control_id}: {e}")

    return True


async def assign_policy(
    client: AgentControlClient,
    agent_uuid: str,
    policy_id: int
) -> bool:
    """Assign policy to agent."""
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
    """Run the email safety control setup."""
    print("\n" + "=" * 70)
    print("EMAIL SAFETY DEMO - CRITICAL CONTROL SETUP")
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
            policy_name = "email-safety-policy"
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
✅ Email Safety Demo Ready

CRITICAL SCENARIO: Prevent PII Leakage in Customer Emails

🛡️ Safety Layer (AgentControl) - HARD BLOCKS:
  • block-pii-in-emails
    - Blocks: SSN, Credit Cards, Phone Numbers in email body
    - Action: DENY (hard block before sending)
    - Compliance: GDPR, PCI-DSS

  • block-credentials-in-emails
    - Blocks: API keys, passwords, tokens in email body
    - Action: DENY (hard block before sending)
    - Security: Credential protection

  • block-internal-info-in-emails
    - Blocks: Database names, server IPs, internal paths
    - Action: DENY (hard block before sending)
    - Security: Information disclosure prevention

✨ Quality Layer (Strands Steering):
  • EmailQualityHandler.steer_after_model()
    - Detects when AgentControl blocked email
    - Guides agent to rephrase without PII
    - Provides better customer experience

Test scenarios:
  ✅ "Send password reset to john@example.com" → Safe, email sent
  🛡️ "Send confirmation for account 123-45-6789" → BLOCKED (SSN detected)
     → Steering guides rephrasing → Email sent without PII
  🛡️ "Send payment confirmation for card 4532-1234-5678-9010" → BLOCKED (CC)
     → Steering guides rephrasing → Email sent without PII

Run the demo:
  streamlit run email_safety_demo.py

This demonstrates why AgentControl is CRITICAL for autonomous agents!
""")

        except Exception as e:
            print(f"\n\n❌ Setup failed: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
