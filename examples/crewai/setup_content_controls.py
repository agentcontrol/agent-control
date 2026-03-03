"""
Setup script for CrewAI customer support PII protection controls.

This script creates PII detection and unauthorized access prevention controls.
Run this once before running content_agent_protection.py.

Usage:
    uv run setup_content_controls.py
"""

import asyncio
import os

from agent_control import Agent, AgentControlClient, agents, controls

AGENT_ID = "989d84f0-9afe-4fb2-9e9e-e9d076271e29"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def setup_content_controls():
    """Create PII protection/unauthorized-access controls and add them directly to the agent."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register Agent
        agent_name = AGENT_ID

        agent = Agent(
            agent_name=agent_name,
            agent_description="Customer support crew with PII protection and access controls"
        )

        try:
            await agents.register_agent(client, agent, steps=[])
            print(f"✓ Agent registered: {AGENT_ID}")
        except Exception as e:
            print(f"ℹ️  Agent might already exist: {e}")

        # 2. Create Unauthorized Access Control (input check)
        unauthorized_access_control_data = {
            "description": "Block requests for other users' data or admin access (PRE-execution)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["handle_ticket"],
                "stages": ["pre"]  # Check input before processing
            },
            "selector": {
                "path": "input.ticket"
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    # Block requests for other users' data, admin access, passwords
                    "pattern": r"(?i)(show\s+me|what\s+is|give\s+me|tell\s+me).*(other\s+user|another\s+user|user\s+\w+|admin|password|credential|account\s+\d+|all\s+orders|other\s+customer)"
                }
            },
            "action": {"decision": "deny"}
        }

        try:
            unauthorized_control = await controls.create_control(
                client,
                name="unauthorized-access-prevention",
                data=unauthorized_access_control_data
            )
            unauthorized_control_id = unauthorized_control["control_id"]
            print(f"✓ Unauthorized Access Control created (ID: {unauthorized_control_id})")
        except Exception as e:
            if "409" in str(e):
                print(f"ℹ️  Unauthorized Access Control already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="unauthorized-access-prevention", limit=1
                )
                if controls_list["controls"]:
                    unauthorized_control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {unauthorized_control_id})")
                else:
                    print("❌ Could not find existing control")
                    raise SystemExit(1)
            else:
                raise

        # 3. Create PII Detection Control (output check)
        pii_detection_control_data = {
            "description": "Block PII (SSN, credit cards, emails, phones) in generated responses (POST-execution)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["handle_ticket"],
                "stages": ["post"]  # Check output after generation
            },
            "selector": {
                "path": "output"
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    # Block SSN, credit cards, emails, phone numbers
                    "pattern": r"(?:\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b)"
                }
            },
            "action": {"decision": "deny"}
        }

        try:
            pii_control = await controls.create_control(
                client,
                name="pii-detection-output",
                data=pii_detection_control_data
            )
            pii_control_id = pii_control["control_id"]
            print(f"✓ PII Detection Control created (ID: {pii_control_id})")
        except Exception as e:
            if "409" in str(e):
                print(f"ℹ️  PII Detection Control already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="pii-detection-output", limit=1
                )
                if controls_list["controls"]:
                    pii_control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {pii_control_id})")
                else:
                    print("❌ Could not find existing control")
                    raise SystemExit(1)
            else:
                raise

        # 4. Create Final Output Validation Control (catches agent-generated PII)
        final_output_control_data = {
            "description": "Block PII in final crew output (catches orchestration bypass where agent generates PII)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["validate_final_output"],
                "stages": ["post"]  # Check output after validation function
            },
            "selector": {
                "path": "output"
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    # Block SSN, credit cards, emails, phone numbers
                    "pattern": r"(?:\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b)"
                }
            },
            "action": {"decision": "deny"}
        }

        try:
            final_output_control = await controls.create_control(
                client,
                name="final-output-pii-detection",
                data=final_output_control_data
            )
            final_output_control_id = final_output_control["control_id"]
            print(f"✓ Final Output Validation Control created (ID: {final_output_control_id})")
        except Exception as e:
            if "409" in str(e):
                print(f"ℹ️  Final Output Validation Control already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="final-output-pii-detection", limit=1
                )
                if controls_list["controls"]:
                    final_output_control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {final_output_control_id})")
                else:
                    print("❌ Could not find existing control")
                    raise SystemExit(1)
            else:
                raise

        # 6. Associate controls directly with agent
        try:
            await agents.add_agent_control(client, agent_name, unauthorized_control_id)
            print("✓ Added unauthorized access control to agent")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print("ℹ️  Unauthorized access control already associated with agent (OK)")
            else:
                print(f"❌ Failed to add unauthorized access control to agent: {e}")
                raise

        try:
            await agents.add_agent_control(client, agent_name, pii_control_id)
            print("✓ Added PII detection control to agent")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print("ℹ️  PII detection control already associated with agent (OK)")
            else:
                print(f"❌ Failed to add PII detection control to agent: {e}")
                raise

        try:
            await agents.add_agent_control(client, agent_name, final_output_control_id)
            print("✓ Added final output validation control to agent")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print("ℹ️  Final output validation control already associated with agent (OK)")
            else:
                print(f"❌ Failed to add final output validation control to agent: {e}")
                raise

        print("\n✅ Setup complete! You can now run content_agent_protection.py")


if __name__ == "__main__":
    print("=" * 60)
    print("CrewAI Customer Support PII Protection Setup")
    print("=" * 60)
    print()

    asyncio.run(setup_content_controls())
