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

from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env", override=False)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../sdks/python/src"))

from agent_control import Agent, AgentControlClient, agents, controls


# Configuration
AGENT_NAME = "banking-email-agent"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


# CRITICAL SAFETY CONTROLS
SAFETY_CONTROLS = [
    # Control 1: Detect PII in LLM output (draft) and steer redaction
    {
        "name": "steer-pii-redaction-llm-output",
        "description": "STEER: Guide PII redaction in LLM draft output",
        "definition": {
            "description": "Guide agent to redact PII in draft before tool call",
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
                    "pattern": r"(\b\d{9,12}\b)|(\d{3}[-\s]?\d{2}[-\s]?\d{4})|(\$[\d,]+\d{3,})"
                }
            },
            "action": {
                "decision": "steer",
                "message": "PII detected in draft - redact before sending",
                "steering_context": {
                    "message": """⚠️ FINANCIAL PII DETECTED - Apply redactions before sending email:

🔒 Redaction Rules (PCI-DSS Standard):
  • Account numbers: Mask all but last 4 digits
    Example: "123456789012" → "****9012" or "XXXX-XXXX-9012"
    Text format: "account ending in 9012" (no full number)

  • SSN: Remove entirely or mask all but last 4
    Example: "123-45-6789" → "***-**-6789" or remove completely
    Text format: "SSN ending in 6789" or omit

  • Large amounts (>$10,000): Round to nearest thousand
    Example: "$45,234.56" → "$45K" or "approximately $45,000"

  • Transaction amounts: Generalize without exact figures
    Example: "$15,000 deposit" → "recent deposit activity"

✅ Critical Requirements:
  - Show ONLY last 4 digits of account/card numbers
  - Mask or remove first 8+ digits completely
  - Never include full SSN, routing numbers, or PINs
  - Round large balances for privacy
  - Generalize transaction types without exact amounts
    """
                }
            },
            "tags": ["pii", "gdpr", "pci-dss", "steer", "llm"]
        }
    },

    # Control 2: Detect credentials/API keys (DENY - hard block)
    {
        "name": "deny-credentials",
        "description": "DENY: Block credentials or API keys in emails (HARD BLOCK)",
        "definition": {
            "description": "Prevent credential leakage - hard block if detected",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "stages": ["pre"],
                "step_names": ["send_monthly_account_summary"]
            },
            "selector": {"path": "input.summary_text"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Match patterns like: api_key, password, secret, token
                    "pattern": r"(api[_-]?key|password|secret|token|credential)[\s:=]+['\"]?[\w\-]{8,}"
                }
            },
            "action": {
                "decision": "deny",
                "message": "Credentials detected in email - BLOCKED for security"
            },
            "tags": ["credentials", "secrets", "critical", "deny"]
        }
    },

    # Control 3: Detect internal system info (DENY - hard block)
    {
        "name": "deny-internal-info",
        "description": "DENY: Block internal system information in emails (HARD BLOCK)",
        "definition": {
            "description": "Prevent exposure of internal database names, server IPs - hard block",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "stages": ["pre"],
                "step_names": ["send_monthly_account_summary"]
            },
            "selector": {"path": "input.summary_text"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Match database names, server paths
                    "pattern": r"(database|db_|server|localhost|127\.0\.0\.1|/var/|/etc/|C:\\\\)"
                }
            },
            "action": {
                "decision": "deny",
                "message": "Internal system info detected in email - BLOCKED for security"
            },
            "tags": ["internal-info", "security", "deny"]
        }
    },
]


async def create_agent(client: AgentControlClient) -> str:
    """Create the email safety demo agent."""
    print("\n" + "=" * 70)
    print("STEP 1: Creating Email Safety Demo Agent")
    print("=" * 70)

    agent = Agent(
        agent_name=AGENT_NAME,
        agent_description="Email safety demo - prevents PII leakage in automated emails"
    )

    try:
        await agents.register_agent(client, agent, steps=[])
        print(f"✓ Agent registered: {AGENT_NAME}")
        return AGENT_NAME
    except Exception as e:
        print(f"ℹ️  Agent might already exist: {e}")
        return AGENT_NAME


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
    """Create safety controls (steer + deny)."""
    print("\n" + "=" * 70)
    print("STEP 2: Creating Safety Controls (Steer + Deny)")
    print("=" * 70)

    control_ids = []

    for control_spec in SAFETY_CONTROLS:
        name = control_spec["name"]
        description = control_spec["description"]
        definition = control_spec["definition"]
        action = definition['action']['decision'].upper()

        icon = "🎯" if action == "STEER" else "🛡️"
        print(f"\n{icon} Creating control: {name}")
        print(f"   {description}")
        print(f"   Action: {action}")

        control_id = await create_control_with_retry(client, name, definition)
        control_ids.append(control_id)
        print(f"   ✓ Control created with ID: {control_id}")

    print(f"\n✓ Created {len(control_ids)} safety control(s)")
    return control_ids


async def attach_controls_to_agent(
    client: AgentControlClient,
    agent_name: str,
    control_ids: list[int],
) -> None:
    """Attach controls directly to the agent."""
    print("\nAttaching controls to agent...")
    for control_id in control_ids:
        try:
            await agents.add_agent_control(client, agent_name, control_id)
            print(f"  ✓ Attached control {control_id}")
        except Exception as e:
            print(f"  ✗ Failed to attach control {control_id}: {e}")


async def main():
    """Run the email safety control setup."""
    print("\n" + "=" * 70)
    print("EMAIL SAFETY DEMO - CONTROL SETUP (AgentControl Steer)")
    print("=" * 70)
    print(f"\nServer URL: {SERVER_URL}")
    print(f"Agent: {AGENT_NAME}")

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
            agent_name = await create_agent(client)

            # 2. Create safety controls
            control_ids = await create_safety_controls(client)
            await attach_controls_to_agent(client, agent_name, control_ids)

            # Success summary
            print("\n" + "=" * 70)
            print("SETUP COMPLETE!")
            print("=" * 70)
            print(f"""
✅ Email Safety Demo Ready - Dual-Plugin AgentControl Integration

ARCHITECTURE: LLM Steer + Tool Deny (Clean Two-Layer Design)

🎯 Layer 1: LLM Post-Output STEER (Primary PII Protection)
  • steer-pii-redaction-llm-output
    - Scope: LLM output (draft stage)
    - Detects: Account numbers, SSN, large amounts in draft text
    - Action: STEER via Strands Guide()
    - Steering Context: Specific redaction instructions
      → "Account 123456789012 → account ending in 9012"
      → "SSN 123-45-6789 → Remove entirely"
      → "$45,234.56 → $45K (rounded)"
    - Compliance: GDPR, PCI-DSS
    - Handler: AgentControlSteeringHandler

🛡️ Layer 2: Tool Pre-Execution DENY (Hard Blocks)
  • deny-credentials
    - Scope: Tool input at send_monthly_account_summary
    - Blocks: API keys, passwords, tokens
    - Action: DENY (RuntimeError - hard block)
    - Handler: AgentControlPlugin

  • deny-internal-info
    - Scope: Tool input at send_monthly_account_summary
    - Blocks: Database names, server IPs, internal paths
    - Action: DENY (RuntimeError - hard block)
    - Handler: AgentControlPlugin

✨ Dual-Plugin Integration:
  Plugin 1: AgentControlSteeringHandler (LLM post) → Guide() for PII
  Plugin 2: AgentControlPlugin (tool pre/post) → RuntimeError for deny

🔄 Flow:
  1. Agent looks up account data
  2. Agent drafts email with PII (e.g., "Account 123456789012")
  3. 🎯 AgentControlSteeringHandler checks LLM output
     → steer-pii-redaction-llm-output matches → Guide()
  4. Agent retries with redaction guidance
  5. Agent calls send_monthly_account_summary() with redacted text
  6. 🛡️ AgentControlPlugin checks tool input
     → deny-credentials: ✅ pass
     → deny-internal-info: ✅ pass
  7. Email sent successfully!

Test scenarios:
  ✅ "Send summary to john@example.com"
     → Draft includes PII → STEER → Redact → Send ✓
  ❌ "Send password: secret123"
     → DENY at tool stage → Blocked 🚫

Run the demo:
  streamlit run email_safety_demo.py

Clean architecture: Single steer at draft stage + deny checks at tool stage!
""")

        except Exception as e:
            print(f"\n\n❌ Setup failed: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
