"""
Setup script for Banking Transaction Agent controls.

Demonstrates all AgentControl action types in a realistic banking scenario:
- ALLOW: Simple transfers that satisfy controls
- DENY: Compliance violations (sanctioned countries, fraud)
- STEER: Large transfers requiring verification and approval

Run this once before running the autonomous agent demo.
"""

import asyncio
import os

from agent_control import Agent, AgentControlClient, agents, controls

AGENT_ID = "f8e5d3c2-4b1a-4e7f-9c8d-2a3b4c5d6e7f"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def setup_banking_controls():
    """Create banking controls demonstrating allow, deny, and steer actions."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register Agent
        agent = Agent(
            agent_name="banking-transaction-agent",
            agent_description="AI agent that processes wire transfers with compliance and fraud controls"
        )

        try:
            await agents.register_agent(client, agent, steps=[])
            print(f"✓ Agent registered: {AGENT_ID}")
        except Exception as e:
            print(f"ℹ️  Agent might already exist: {e}")

        print("\n📋 Creating banking controls...")

        # ============================================================================
        # DENY CONTROLS - Hard blocks for compliance violations
        # ============================================================================

        # Control 1: Block Sanctioned Countries (DENY)
        sanctioned_countries_control = {
            "description": "Block transfers to OFAC sanctioned countries",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["process_wire_transfer"],
                "stages": ["pre"]
            },
            "selector": {
                "path": "input.destination_country"
            },
            "evaluator": {
                "name": "list",
                "config": {
                    "values": ["north korea", "iran", "syria", "cuba", "crimea"],
                    "logic": "any",
                    "match_mode": "contains",
                    "case_sensitive": False
                }
            },
            "action": {
                "decision": "deny"
            }
        }

        # Control 2: Block High Fraud Risk (DENY)
        fraud_risk_control = {
            "description": "Block transactions with high fraud risk scores",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["process_wire_transfer"],
                "stages": ["pre"]
            },
            "selector": {
                "path": "input"
            },
            "evaluator": {
                "name": "json",
                "config": {
                    "field_constraints": {
                        "fraud_score": {
                            "type": "number",
                            "max": 0.8
                        }
                    }
                }
            },
            "action": {
                "decision": "deny"
            }
        }

        # ============================================================================
        # WARN CONTROLS - Log suspicious activity without blocking
        # ============================================================================

        # Control 3: New Recipient Warning (WARN)
        new_recipient_control = {
            "description": "Log warning when transferring to a new recipient",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["process_wire_transfer"],
                "stages": ["pre"]
            },
            "selector": {
                "path": "input.recipient"
            },
            "evaluator": {
                "name": "list",
                "config": {
                    "values": ["John Smith", "Acme Corp", "Global Suppliers Inc"],
                    "match_type": "not_in",
                    "case_sensitive": False
                }
            },
            "action": {
                "decision": "warn"
            }
        }

        # ============================================================================
        # STEER CONTROLS - Guide agent through approval workflows
        # ============================================================================

        # Control 4: Large Transfer Verification (STEER)
        large_transfer_control = {
            "description": "Require verification for large transfers",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["process_wire_transfer"],
                "stages": ["pre"]
            },
            "selector": {
                "path": "input"
            },
            "evaluator": {
                "name": "json",
                "config": {
                    "json_schema": {
                        "type": "object",
                        "oneOf": [
                            {"properties": {"amount": {"type": "number", "exclusiveMaximum": 10000}}},
                            {"properties": {"amount": {"type": "number", "minimum": 10000}, "verified_2fa": {"const": True}}}
                        ]
                    }
                }
            },
            "action": {
                "decision": "steer",
                "steering_context": {
                    "message": "{\"required_actions\": [\"request_2fa\", \"verify_2fa\"], \"retry_flags\": {\"verified_2fa\": true}, \"reason\": \"Large transfer requires identity verification via 2FA\"}"
                }
            }
        }

        # Control 5: Manager Approval Required (STEER)
        manager_approval_control = {
            "description": "Require manager approval for transfers exceeding daily limits",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["process_wire_transfer"],
                "stages": ["pre"]
            },
            "selector": {
                "path": "input"
            },
            "evaluator": {
                "name": "json",
                "config": {
                    "json_schema": {
                        "type": "object",
                        "oneOf": [
                            {"properties": {"amount": {"type": "number", "exclusiveMaximum": 10000}}},
                            {"properties": {"amount": {"type": "number", "minimum": 10000}, "manager_approved": {"const": True}}}
                        ]
                    }
                }
            },
            "action": {
                "decision": "steer",
                "steering_context": {
                    "message": "{\"required_actions\": [\"justification\", \"approval\"], \"steps\": [{\"step\": 1, \"action\": \"justification\", \"description\": \"Request business justification from user for this large transfer\"}, {\"step\": 2, \"action\": \"approval\", \"description\": \"Submit transfer details and justification to manager for approval\"}], \"retry_flags\": {\"manager_approved\": true, \"justification\": \"<collected_from_user>\"}, \"reason\": \"Transfer exceeds daily limit - requires sequential justification and manager approval\"}"
                }
            }
        }

        # Create all controls
        control_configs = [
            ("deny-sanctioned-countries", sanctioned_countries_control),
            ("deny-high-fraud-risk", fraud_risk_control),
            ("warn-new-recipient", new_recipient_control),
            ("steer-large-transfer-verification", large_transfer_control),
            ("steer-manager-approval-required", manager_approval_control),
        ]

        control_ids = []
        for control_name, control_data in control_configs:
            try:
                control_result = await controls.create_control(
                    client,
                    name=control_name,
                    data=control_data
                )
                control_id = control_result["control_id"]
                print(f"  ✓ Created control: {control_name} (ID: {control_id})")
                control_ids.append(control_id)
            except Exception as e:
                if "409" in str(e):
                    print(f"  ℹ️  Control '{control_name}' already exists, looking it up...")
                    controls_list = await controls.list_controls(
                        client, name=control_name, limit=1
                    )
                    if controls_list["controls"]:
                        control_id = controls_list["controls"][0]["id"]
                        print(f"  ℹ️  Using existing control (ID: {control_id})")
                        control_ids.append(control_id)
                    else:
                        print(f"  ❌ Could not find existing control '{control_name}'")
                        raise
                else:
                    print(f"  ❌ Error creating control '{control_name}': {e}")
                    if hasattr(e, 'response'):
                        try:
                            error_detail = e.response.json()
                            print(f"  Details: {error_detail}")
                        except:
                            print(f"  Response: {e.response.text if hasattr(e.response, 'text') else e.response}")
                    raise

        # 3. Associate controls directly with the agent
        print("\n📋 Associating controls directly with agent...")
        for control_id in control_ids:
            try:
                await agents.add_agent_control(client, agent.agent_name, control_id)
                print(f"  ✓ Added control {control_id} to agent")
            except Exception as e:
                if "409" in str(e) or "already" in str(e).lower():
                    print(f"  ℹ️  Control {control_id} already associated with agent (OK)")
                else:
                    print(f"  ⚠️  Failed to add control: {e}")

        print("\n✅ Setup complete!")
        print(f"\nAgent ID: {AGENT_ID}")
        print(f"Server URL: {SERVER_URL}")
        print("\n📚 Controls created:")
        print("  DENY:")
        print("    • Sanctioned countries (OFAC compliance)")
        print("    • High fraud risk (score > 0.8)")
        print("  STEER:")
        print("    • Large transfer 2FA verification (>$10k)")
        print("    • Manager approval for over-limit transfers")
        print("\nYou can now run: uv run autonomous_agent_demo.py")


if __name__ == "__main__":
    asyncio.run(setup_banking_controls())
