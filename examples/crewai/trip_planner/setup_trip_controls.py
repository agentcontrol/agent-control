"""
Setup script for Trip Planner controls with Agent Control.

This script creates controls for:
1. Budget validation - Block unreasonable budget requests
2. PII detection - Block PII in trip planning outputs
3. Scam prevention - Block suspicious travel requests

Usage:
    uv run setup_trip_controls.py
"""

import asyncio
import os
import uuid

import agent_control
from agent_control import Agent, AgentControlClient, agents, controls, policies

AGENT_ID = "trip-planner-crew"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
POLICY_ID_OVERRIDE = os.getenv("TRIP_POLICY_ID")


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in version.split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)


async def setup_trip_controls():
    """Create trip planner controls, policy, and assign to agent."""
    # Ensure compatible SDK version (server expects 3.x payloads)
    sdk_version = getattr(agent_control, "__version__", "0.0.0")
    if _parse_version_tuple(sdk_version) < (3, 0, 0):
        raise SystemExit(
            f"Incompatible agent-control SDK version: {sdk_version}. "
            "Recreate the example venv and run via `uv run` to install >=3.0.0."
        )

    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register Agent
        agent_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID)

        agent = Agent(
            agent_id=agent_uuid,
            agent_name="Trip Planner Crew",
            agent_description="Multi-agent trip planning crew with budget and PII protection",
        )

        try:
            await agents.register_agent(client, agent, steps=[])
            print(f"✓ Agent registered: {AGENT_ID}")
        except Exception as e:
            print(f"ℹ️  Agent registration skipped: {e}")

        # 2. Create Budget Validation Control (input check)
        # Blocks requests with unreasonable budgets or suspicious financial requests
        budget_control_data = {
            "description": "Block unreasonable budget requests or suspicious financial patterns (PRE-execution)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["plan_trip"],
                "stages": ["pre"],  # Check input before processing
            },
            "selector": {"path": "input.interests"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Block suspicious patterns: zero budget, "free", wire transfers, crypto payments
                    "pattern": r"(?i)(zero\s+budget|\$0|free\s+trip|wire\s+transfer|bitcoin|crypto|western\s+union|money\s+order|prepaid\s+card|gift\s+card\s+payment)"
                },
            },
            "action": {"decision": "deny"},
        }

        try:
            budget_control = await controls.create_control(
                client, name="trip-budget-validation", data=budget_control_data
            )
            budget_control_id = budget_control["control_id"]
            print(f"✓ Budget Validation Control created (ID: {budget_control_id})")
        except Exception as e:
            if "409" in str(e):
                print("ℹ️  Budget Validation Control already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="trip-budget-validation", limit=1
                )
                if controls_list["controls"]:
                    budget_control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {budget_control_id})")
                else:
                    print("❌ Could not find existing control")
                    raise SystemExit(1)
            else:
                raise

        # 3. Create Scam Prevention Control (input check)
        # Blocks requests that look like travel scams
        scam_control_data = {
            "description": "Block suspicious travel scam patterns (PRE-execution)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["plan_trip"],
                "stages": ["pre"],
            },
            "selector": {"path": "input.interests"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Block scam patterns: fake contests, urgency pressure, too-good-to-be-true offers
                    "pattern": r"(?i)(won\s+a\s+trip|free\s+vacation\s+winner|claim\s+your\s+prize|urgent.*book\s+now|limited\s+time.*free|all\s+expenses\s+paid.*winner|verify\s+your\s+identity|send\s+deposit|advance\s+fee)"
                },
            },
            "action": {"decision": "deny"},
        }

        try:
            scam_control = await controls.create_control(
                client, name="trip-scam-prevention", data=scam_control_data
            )
            scam_control_id = scam_control["control_id"]
            print(f"✓ Scam Prevention Control created (ID: {scam_control_id})")
        except Exception as e:
            if "409" in str(e):
                print("ℹ️  Scam Prevention Control already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="trip-scam-prevention", limit=1
                )
                if controls_list["controls"]:
                    scam_control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {scam_control_id})")
                else:
                    print("❌ Could not find existing control")
                    raise SystemExit(1)
            else:
                raise

        # 4. Create PII Detection Control (output check)
        # Blocks PII (credit cards, SSN, etc.) in generated trip plans
        pii_control_data = {
            "description": "Block PII (SSN, credit cards, personal identifiers) in trip planning outputs (POST-execution)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["plan_trip"],
                "stages": ["post"],  # Check output after generation
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Block SSN, credit cards, passport numbers, and common account number phrases.
                    # Note: RE2 does not support lookarounds, so we avoid (?=...) patterns.
                    "pattern": r"(?:\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Z]{1,2}\d{6,9}\b|\b(?:account|acct)\s*(?:number|no\.?)?\s*\d{6,12}\b)"
                },
            },
            "action": {"decision": "deny"},
        }

        try:
            pii_control = await controls.create_control(
                client, name="trip-pii-detection", data=pii_control_data
            )
            pii_control_id = pii_control["control_id"]
            print(f"✓ PII Detection Control created (ID: {pii_control_id})")
        except Exception as e:
            if "409" in str(e):
                print("ℹ️  PII Detection Control already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="trip-pii-detection", limit=1
                )
                if controls_list["controls"]:
                    pii_control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {pii_control_id})")
                else:
                    print("❌ Could not find existing control")
                    raise SystemExit(1)
            else:
                raise

        # 5. Create Final Output Validation Control
        final_output_control_data = {
            "description": "Block PII in final trip plan output (catches orchestration bypass)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["validate_trip_output"],
                "stages": ["post"],
            },
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    # Block SSN, credit cards, passport numbers
                    "pattern": r"(?:\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\b[A-Z]{1,2}\d{6,9}\b)"
                },
            },
            "action": {"decision": "deny"},
        }

        try:
            final_control = await controls.create_control(
                client, name="trip-final-output-validation", data=final_output_control_data
            )
            final_control_id = final_control["control_id"]
            print(f"✓ Final Output Validation Control created (ID: {final_control_id})")
        except Exception as e:
            if "409" in str(e):
                print("ℹ️  Final Output Validation Control already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="trip-final-output-validation", limit=1
                )
                if controls_list["controls"]:
                    final_control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {final_control_id})")
                else:
                    print("❌ Could not find existing control")
                    raise SystemExit(1)
            else:
                raise

        # 6. Create Policy (or reuse if TRIP_POLICY_ID is provided)
        policy_id: int | None = None
        if POLICY_ID_OVERRIDE:
            try:
                policy_id = int(POLICY_ID_OVERRIDE)
                print(f"ℹ️  Using existing policy ID from TRIP_POLICY_ID={policy_id}")
            except ValueError as e:
                raise SystemExit(
                    f"Invalid TRIP_POLICY_ID='{POLICY_ID_OVERRIDE}'. Must be an integer."
                ) from e

        if policy_id is None:
            try:
                policy_result = await policies.create_policy(
                    client, name="trip-planner-protection-policy"
                )
                policy_id = policy_result["policy_id"]
                print(f"✓ Policy created (ID: {policy_id})")
            except Exception as e:
                if "409" in str(e):
                    print("⚠️  Policy 'trip-planner-protection-policy' already exists.")
                    print("    Provide TRIP_POLICY_ID to reuse it, then re-run.")
                    print("    Example:")
                    print("      export TRIP_POLICY_ID=<policy_id>")
                    raise SystemExit(1)
                raise

        # 7. Add Controls to Policy
        for control_id, control_name in [
            (budget_control_id, "budget validation"),
            (scam_control_id, "scam prevention"),
            (pii_control_id, "PII detection"),
            (final_control_id, "final output validation"),
        ]:
            try:
                await policies.add_control_to_policy(client, policy_id, control_id)
                print(f"✓ Added {control_name} control to policy")
            except Exception as e:
                if "409" in str(e) or "already" in str(e).lower():
                    print(f"ℹ️  {control_name.capitalize()} control already in policy (OK)")
                else:
                    print(f"❌ Failed to add control to policy: {e}")
                    raise

        # 8. Assign Policy to Agent
        try:
            await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
            print("✓ Assigned policy to agent")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print("ℹ️  Policy already assigned to agent (OK)")
            else:
                print(f"❌ Failed to assign policy: {e}")
                raise

        print("\n✅ Setup complete! You can now run trip_planner_protection.py")


if __name__ == "__main__":
    print("=" * 60)
    print("Trip Planner Agent Control Setup")
    print("=" * 60)
    print()

    asyncio.run(setup_trip_controls())
