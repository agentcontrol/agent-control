#!/usr/bin/env python3
"""
Script to update existing controls on the server.

This script demonstrates updating the SSN control to allow SSNs instead of blocking them.

Prerequisites:
    - Agent Control server running at http://localhost:8000
    - Run setup_controls.py first to create the controls

Usage:
    # Allow SSNs (disable the control)
    uv run python examples/agent_control_demo/update_controls.py --allow-ssn

    # Block SSNs again (re-enable the control)
    uv run python examples/agent_control_demo/update_controls.py --block-ssn
"""

import asyncio
import os
import sys
# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

from agent_control import AgentControlClient

# Configuration
AGENT_NAME = "demo-chatbot"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def get_control_by_name(client: AgentControlClient, agent_name: str, name: str) -> dict | None:
    """Find a control by name from the agent's controls."""
    try:
        response = await client.http_client.get(f"/api/v1/agents/{agent_name}/controls")
        response.raise_for_status()
        controls = response.json().get("controls", [])

        for ctrl in controls:
            if ctrl.get("name") == name:
                return ctrl

        return None
    except Exception as e:
        print(f"✗ Failed to get controls: {e}")
        return None


async def allow_ssn(client: AgentControlClient, control_id: int) -> None:
    """Update the SSN control to ALLOW SSNs (disable the control)."""
    print("\n" + "=" * 60)
    print("Updating SSN Control: ALLOW SSNs")
    print("=" * 60)

    # Disable the control - SSNs will now be allowed through
    updated_definition = {
        "description": "SSN control - DISABLED (SSNs allowed)",
        "enabled": False,  # Disabled = SSNs allowed
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
                    "flags": []
                }
            },
        },
        "action": {"decision": "deny"},
        "tags": ["pii", "ssn", "output-filter", "disabled"]
    }

    print(f"  Control ID: {control_id}")
    print(f"  Setting enabled: False")
    print(f"  Result: SSNs will now pass through")

    try:
        response = await client.http_client.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": updated_definition}
        )
        response.raise_for_status()
        print(f"\n✓ SSN control disabled - SSNs are now ALLOWED")
    except Exception as e:
        print(f"\n✗ Failed to update control: {e}")
        raise


async def block_ssn(client: AgentControlClient, control_id: int) -> None:
    """Update the SSN control to BLOCK SSNs (re-enable the control)."""
    print("\n" + "=" * 60)
    print("Updating SSN Control: BLOCK SSNs")
    print("=" * 60)

    # Re-enable the control - SSNs will be blocked
    updated_definition = {
        "description": "Block SSN patterns in output to prevent PII leakage",
        "enabled": True,  # Enabled = SSNs blocked
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
                    "flags": []
                }
            },
        },
        "action": {"decision": "deny"},
        "tags": ["pii", "ssn", "output-filter"]
    }

    print(f"  Control ID: {control_id}")
    print(f"  Setting enabled: True")
    print(f"  Result: SSNs will now be BLOCKED")

    try:
        response = await client.http_client.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": updated_definition}
        )
        response.raise_for_status()
        print(f"\n✓ SSN control enabled - SSNs are now BLOCKED")
    except Exception as e:
        print(f"\n✗ Failed to update control: {e}")
        raise


async def show_current_status(client: AgentControlClient, agent_name: str) -> None:
    """Show the current status of the SSN control."""
    print("\n" + "=" * 60)
    print("Current SSN Control Status")
    print("=" * 60)

    ctrl = await get_control_by_name(client, agent_name, "block-ssn-output")
    if ctrl:
        ctrl_def = ctrl.get("control", {})
        enabled = ctrl_def.get("enabled", True)
        status = "BLOCKING SSNs" if enabled else "ALLOWING SSNs"
        print(f"  Control: {ctrl.get('name')}")
        print(f"  ID: {ctrl.get('id')}")
        print(f"  Enabled: {enabled}")
        print(f"  Status: {status}")
    else:
        print("  ✗ SSN control not found. Run setup_controls.py first.")


async def main():
    """Run the control update demo."""
    import argparse
    parser = argparse.ArgumentParser(description="Update SSN control")
    parser.add_argument("--allow-ssn", action="store_true", help="Allow SSNs (disable control)")
    parser.add_argument("--block-ssn", action="store_true", help="Block SSNs (enable control)")
    parser.add_argument("--status", action="store_true", help="Show current status")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("AGENT CONTROL DEMO: Update Controls")
    print("=" * 60)
    print(f"\nServer URL: {SERVER_URL}")
    print(f"Agent Name: {AGENT_NAME}")

    async with AgentControlClient(base_url=SERVER_URL) as client:
        # Check server health
        try:
            await client.health_check()
        except Exception as e:
            print(f"\n✗ Server not available: {e}")
            print("\nMake sure the server is running:")
            print("  cd server && make run")
            return

        # Find the SSN control
        ctrl = await get_control_by_name(client, AGENT_NAME, "block-ssn-output")
        if not ctrl:
            print("\n✗ SSN control not found!")
            print("  Run setup_controls.py first:")
            print("  uv run python examples/agent_control_demo/setup_controls.py")
            return

        control_id = ctrl.get("id")

        if args.status:
            await show_current_status(client, AGENT_NAME)
        elif args.allow_ssn:
            await allow_ssn(client, control_id)
            await show_current_status(client, AGENT_NAME)
        elif args.block_ssn:
            await block_ssn(client, control_id)
            await show_current_status(client, AGENT_NAME)
        else:
            # Default: show status and usage
            await show_current_status(client, AGENT_NAME)
            print("\n" + "=" * 60)
            print("Usage")
            print("=" * 60)
            print("""
To allow SSNs (disable the control):
  uv run python examples/agent_control_demo/update_controls.py --allow-ssn

To block SSNs (re-enable the control):
  uv run python examples/agent_control_demo/update_controls.py --block-ssn

Then test with the demo agent:
  uv run python examples/agent_control_demo/demo_agent.py
""")


if __name__ == "__main__":
    asyncio.run(main())
