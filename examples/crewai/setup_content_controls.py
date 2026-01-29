"""
Setup script for CrewAI customer support PII protection controls.

This script creates PII detection and unauthorized access prevention controls.
Run this once before running content_agent_protection.py.

Usage:
    uv run setup_content_controls.py
"""

import asyncio
import os
import uuid

from agent_control import Agent, AgentControlClient, agents, controls, policies

AGENT_ID = "support-crew-demo"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def setup_content_controls():
    """Create PII protection and unauthorized access controls, policy, and assign to agent."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register Agent
        agent_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID)

        agent = Agent(
            agent_id=agent_uuid,
            agent_name="Customer Support Crew",
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
                "plugin": "regex",
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
                "plugin": "regex",
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
                "plugin": "regex",
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

        # 6. Create Policy
        try:
            policy_result = await policies.create_policy(
                client, name="support-pii-protection-policy"
            )
            policy_id = policy_result["policy_id"]
            print(f"✓ Policy created (ID: {policy_id})")
        except Exception as e:
            if "409" in str(e):
                print(f"⚠️  Policy 'support-pii-protection-policy' already exists.")
                print("    Cannot proceed - SDK doesn't support looking up policies by name.")
                print("\n    To fix this, run one of these commands:")
                print("    1. Delete via server API:")
                print(f"       curl -X DELETE {SERVER_URL}/api/v1/policies/<policy_id>")
                print("    2. Or use the server UI to delete the policy")
                print("\n    Then re-run this script.")
                raise SystemExit(1)
            raise

        # 7. Add Controls to Policy
        try:
            await policies.add_control_to_policy(client, policy_id, unauthorized_control_id)
            print(f"✓ Added unauthorized access control to policy")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print(f"ℹ️  Unauthorized access control already in policy (OK)")
            else:
                print(f"❌ Failed to add control to policy: {e}")
                raise

        try:
            await policies.add_control_to_policy(client, policy_id, pii_control_id)
            print(f"✓ Added PII detection control to policy")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print(f"ℹ️  PII detection control already in policy (OK)")
            else:
                print(f"❌ Failed to add control to policy: {e}")
                raise

        try:
            await policies.add_control_to_policy(client, policy_id, final_output_control_id)
            print(f"✓ Added final output validation control to policy")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print(f"ℹ️  Final output validation control already in policy (OK)")
            else:
                print(f"❌ Failed to add control to policy: {e}")
                raise

        # 8. Assign Policy to Agent
        try:
            await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
            print(f"✓ Assigned policy to agent")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print(f"ℹ️  Policy already assigned to agent (OK)")
            else:
                print(f"❌ Failed to assign policy: {e}")
                raise

        print("\n✅ Setup complete! You can now run content_agent_protection.py")


if __name__ == "__main__":
    print("=" * 60)
    print("CrewAI Customer Support PII Protection Setup")
    print("=" * 60)
    print()

    asyncio.run(setup_content_controls())
