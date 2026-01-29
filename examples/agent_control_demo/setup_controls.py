#!/usr/bin/env python3
"""
Script to create, list, update, and manage controls on the server.

This script demonstrates the full control lifecycle:
1. Create an agent
2. Create controls (regex and list)
3. Create a policy and add controls to it
4. Assign the policy to the agent
5. List controls
6. Update a control

API Structure:
    Agent → Policy → Controls

Prerequisites:
    - Agent Control server running at http://localhost:8000
    - Run: cd server && make run

Usage:
    uv run python examples/agent_control_demo/setup_controls.py
"""

import asyncio
import os
import sys
from uuid import UUID

# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

from agent_control import AgentControlClient


# Configuration
AGENT_NAME = "demo-chatbot"
AGENT_ID = "demo-chatbot-v1"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def create_agent(client: AgentControlClient) -> str:
    """Create or get the demo agent."""
    print("\n" + "=" * 60)
    print("STEP 1: Creating Agent")
    print("=" * 60)

    # Generate a deterministic UUID from the agent ID
    import uuid
    agent_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID)

    try:
        response = await client.http_client.post(
            "/api/v1/agents/initAgent",  # Correct endpoint
            json={
                "agent": {
                    "agent_id": str(agent_uuid),
                    "agent_name": AGENT_NAME,
                    "agent_description": "Demo chatbot for testing controls",
                },
                "steps": []
            }
        )
        response.raise_for_status()
        data = response.json()

        created = data.get("created", False)

        if created:
            print(f"✓ Created new agent: {AGENT_NAME}")
        else:
            print(f"✓ Agent already exists: {AGENT_NAME}")

        print(f"  Agent UUID: {agent_uuid}")
        return str(agent_uuid)

    except Exception as e:
        print(f"✗ Failed to create agent: {e}")
        raise


async def create_control(
    client: AgentControlClient,
    name: str,
    control_definition: dict
) -> int:
    """Create a control with the given definition."""
    try:
        # Step 1: Create the control (just the name)
        response = await client.http_client.put(
            "/api/v1/controls",
            json={"name": name}
        )

        if response.status_code == 409:
            # Control exists, get its ID
            print(f"  ℹ️  Control '{name}' already exists")
            # We need to find the control ID - for now, we'll re-create it
            # In a real app, you'd have a GET endpoint to find by name
            return -1

        response.raise_for_status()
        control_id = response.json().get("control_id")

        # Step 2: Set the control data
        response = await client.http_client.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": control_definition}
        )
        response.raise_for_status()

        print(f"✓ Created control '{name}' with ID: {control_id}")
        return control_id

    except Exception as e:
        print(f"✗ Failed to create control '{name}': {e}")
        raise


async def create_regex_control(client: AgentControlClient) -> int:
    """Create a regex control to block SSN patterns."""
    print("\n" + "=" * 60)
    print("STEP 2: Creating Regex Control")
    print("=" * 60)

    control_definition = {
        "description": "Block SSN patterns in output to prevent PII leakage",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},  # Check AFTER
        "selector": {"path": "output"},
        "evaluator": {
            "name": "regex",
            "config": {
                "pattern": r"\b\d{3}-\d{2}-\d{4}\b",  # SSN pattern
                "flags": []
            }
        },
        "action": {"decision": "deny"},
        "tags": ["pii", "ssn", "output-filter"]
    }

    print(f"Creating control: block-ssn-output")
    print(f"  Type: Regex")
    print(f"  Pattern: {control_definition['evaluator']['config']['pattern']}")
    print(f"  Stages: {', '.join(control_definition['scope']['stages'])}")
    print(f"  Action: {control_definition['action']['decision']}")

    return await create_control(client, "block-ssn-output", control_definition)


async def create_list_control(client: AgentControlClient) -> int:
    """Create a list control to block dangerous SQL keywords."""
    print("\n" + "=" * 60)
    print("STEP 3: Creating List Control")
    print("=" * 60)

    control_definition = {
        "description": "Block dangerous SQL operations in input",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},  # Check BEFORE
        "selector": {"path": "input"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT"],
                "logic": "any",  # Block if ANY keyword is found
                "match_on": "match",
                "match_mode": "contains",  # Substring/keyword matching
                "case_sensitive": False
            }
        },
        "action": {"decision": "deny"},
        "tags": ["sql-injection", "input-filter", "security"]
    }

    print(f"Creating control: block-dangerous-sql")
    print(f"  Type: List")
    print(f"  Values: {control_definition['evaluator']['config']['values']}")
    print(f"  Logic: {control_definition['evaluator']['config']['logic']}")
    print(f"  Stages: {', '.join(control_definition['scope']['stages'])}")
    print(f"  Action: {control_definition['action']['decision']}")

    return await create_control(client, "block-dangerous-sql", control_definition)




async def create_policy(client: AgentControlClient, name: str) -> int:
    """Create a policy."""
    print("\n" + "=" * 60)
    print("STEP 4: Creating Policy")
    print("=" * 60)

    try:
        response = await client.http_client.put(
            "/api/v1/policies",
            json={"name": name}
        )

        if response.status_code == 409:
            print(f"  ℹ️  Policy '{name}' already exists")
            return -1

        response.raise_for_status()
        policy_id = response.json().get("policy_id")

        print(f"✓ Created policy '{name}' with ID: {policy_id}")
        return policy_id

    except Exception as e:
        print(f"✗ Failed to create policy: {e}")
        raise


async def add_control_to_policy(
    client: AgentControlClient,
    policy_id: int,
    control_id: int
) -> bool:
    """Add a control directly to a policy."""
    try:
        response = await client.http_client.post(
            f"/api/v1/policies/{policy_id}/controls/{control_id}"
        )
        response.raise_for_status()
        data = response.json()
        print(f"  ✓ Added control {control_id} to policy {policy_id}")
        print(f"    Response: {data}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to add control to policy: {e}")
        return False


async def assign_policy_to_agent(
    client: AgentControlClient,
    agent_uuid: str,
    policy_id: int
) -> bool:
    """Assign a policy to an agent."""
    print("\n" + "=" * 60)
    print("STEP 5: Assigning Policy to Agent")
    print("=" * 60)

    try:
        response = await client.http_client.post(
            f"/api/v1/agents/{agent_uuid}/policy/{policy_id}"
        )
        response.raise_for_status()
        data = response.json()
        print(f"✓ Assigned policy {policy_id} to agent {agent_uuid}")
        print(f"  Response: {data}")
        return True
    except Exception as e:
        print(f"✗ Failed to assign policy: {e}")
        return False


async def list_agent_controls(client: AgentControlClient, agent_uuid: str) -> list:
    """List all controls for the agent."""
    print("\n" + "=" * 60)
    print("STEP 6: Listing Agent's Controls")
    print("=" * 60)

    try:
        response = await client.http_client.get(
            f"/api/v1/agents/{agent_uuid}/controls"
        )
        response.raise_for_status()
        data = response.json()
        controls = data.get("controls", [])

        print(f"✓ Found {len(controls)} control(s) for agent:\n")

        for ctrl in controls:
            print(f"  📋 Control: {ctrl.get('name', 'unnamed')}")
            print(f"     ID: {ctrl.get('id')}")
            ctrl_def = ctrl.get("control", {})
            print(f"     Enabled: {ctrl_def.get('enabled', True)}")
            print(f"     Type: {ctrl_def.get('evaluator', {}).get('type', 'unknown')}")
            scope = ctrl_def.get("scope", {}) or {}
            stages = scope.get("stages", [])
            stage_label = ", ".join(stages) if stages else "unknown"
            print(f"     Stages: {stage_label}")
            print(f"     Action: {ctrl_def.get('action', {}).get('decision', 'unknown')}")
            print(f"     Tags: {ctrl_def.get('tags', [])}")
            print()

        return controls

    except Exception as e:
        print(f"✗ Failed to list controls: {e}")
        raise


async def update_control(client: AgentControlClient, control_id: int) -> None:
    """Update the list control to add more blocked keywords."""
    print("\n" + "=" * 60)
    print("STEP 7: Updating List Control")
    print("=" * 60)

    updated_definition = {
        "description": "Block dangerous SQL operations (UPDATED - more keywords)",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": [
                    "DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT",
                    "REVOKE", "EXECUTE", "SHUTDOWN", "BACKUP"  # More keywords!
                ],
                "logic": "any",
                "match_on": "match",
                "match_mode": "contains",  # Substring/keyword matching
                "case_sensitive": False
            }
        },
        "action": {"decision": "deny"},
        "tags": ["sql-injection", "input-filter", "security", "updated"]
    }

    print(f"Updating control ID: {control_id}")
    print(f"  Adding keywords: REVOKE, EXECUTE, SHUTDOWN, BACKUP")

    try:
        response = await client.http_client.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": updated_definition}
        )
        response.raise_for_status()
        print(f"✓ Successfully updated control {control_id}")
    except Exception as e:
        print(f"✗ Failed to update control: {e}")
        raise


async def get_control_data(client: AgentControlClient, control_id: int) -> dict:
    """Get a control's data."""
    print("\n" + "=" * 60)
    print("STEP 8: Getting Updated Control")
    print("=" * 60)

    try:
        response = await client.http_client.get(
            f"/api/v1/controls/{control_id}/data"
        )
        response.raise_for_status()
        data = response.json().get("data", {})

        print(f"✓ Retrieved control {control_id}:")
        print(f"  Description: {data.get('description', 'N/A')}")
        print(f"  Evaluator Type: {data.get('evaluator', {}).get('type', 'N/A')}")
        print(f"  Values: {data.get('evaluator', {}).get('config', {}).get('values', [])}")
        print(f"  Tags: {data.get('tags', [])}")

        return data

    except Exception as e:
        print(f"✗ Failed to get control: {e}")
        raise


async def verify_full_chain(client: AgentControlClient, agent_uuid: str) -> None:
    """Debug function to verify the entire chain."""
    print("\n" + "=" * 60)
    print("DEBUG: Verifying Full Chain")
    print("=" * 60)

    # 1. Get agent info
    print("\n1. Agent Info:")
    try:
        resp = await client.http_client.get(f"/api/v1/agents/{agent_uuid}")
        resp.raise_for_status()
        agent_data = resp.json()
        print(f"   Agent: {agent_data}")
    except Exception as e:
        print(f"   Error: {e}")

    # 2. Get agent's policy
    print("\n2. Agent's Policy:")
    try:
        resp = await client.http_client.get(f"/api/v1/agents/{agent_uuid}/policy")
        if resp.status_code == 404:
            print("   No policy assigned to agent")
            policy_id = None
        else:
            resp.raise_for_status()
            policy_data = resp.json()
            policy_id = policy_data.get("policy_id")
            print(f"   Policy ID: {policy_id}")

            if policy_id:
                # 3. Get policy's controls
                print("\n3. Policy's Controls:")
                resp = await client.http_client.get(f"/api/v1/policies/{policy_id}/controls")
                resp.raise_for_status()
                ctrl_data = resp.json()
                control_ids = ctrl_data.get("control_ids", [])
                print(f"   Control IDs: {control_ids}")
    except Exception as e:
        print(f"   Error: {e}")
        policy_id = None

    # 4. Final: List agent controls (the API we're testing)
    print("\n4. Final Agent Controls (via /agents/{id}/controls):")
    try:
        resp = await client.http_client.get(f"/api/v1/agents/{agent_uuid}/controls")
        resp.raise_for_status()
        controls = resp.json()
        print(f"   Controls: {controls}")
    except Exception as e:
        print(f"   Error: {e}")


async def main():
    """Run the control setup demo."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing setup")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("AGENT CONTROL DEMO: Setup Controls")
    print("=" * 60)
    print(f"\nServer URL: {SERVER_URL}")
    print(f"Agent: {AGENT_NAME} ({AGENT_ID})")

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

        # Generate agent UUID
        import uuid
        agent_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID))

        # If verify-only mode, just run verification
        if args.verify_only:
            await verify_full_chain(client, agent_uuid)
            return

        # 1. Create agent
        agent_uuid = await create_agent(client)

        # 2. Create controls
        regex_control_id = await create_regex_control(client)
        list_control_id = await create_list_control(client)

        # Skip remaining steps if controls already existed
        if regex_control_id == -1 or list_control_id == -1:
            print("\n⚠️  Some controls already exist. Running verification...")
            await verify_full_chain(client, agent_uuid)
            return

        # 3. Create policy
        policy_id = await create_policy(client, "demo-policy")
        if policy_id == -1:
            print("\n⚠️  Policy already exists. Running verification...")
            await verify_full_chain(client, agent_uuid)
            return

        # 4. Add controls to policy
        print("\n  Adding controls to policy...")
        ok1 = await add_control_to_policy(client, policy_id, regex_control_id)
        ok2 = await add_control_to_policy(client, policy_id, list_control_id)
        if not (ok1 and ok2):
            print("\n⚠️  Failed to add controls to policy!")

        # Verify: List controls in policy
        print("\n  Verifying policy contents...")
        try:
            resp = await client.http_client.get(
                f"/api/v1/policies/{policy_id}/controls"
            )
            resp.raise_for_status()
            policy_controls = resp.json()
            print(f"  Policy {policy_id} has controls: {policy_controls}")
        except Exception as e:
            print(f"  Failed to verify policy: {e}")

        # 5. Assign policy to agent
        ok3 = await assign_policy_to_agent(client, agent_uuid, policy_id)
        if not ok3:
            print("\n⚠️  Failed to assign policy to agent!")

        # Verify: Get agent's policy
        print("\n  Verifying agent policy assignment...")
        try:
            resp = await client.http_client.get(
                f"/api/v1/agents/{agent_uuid}/policy"
            )
            resp.raise_for_status()
            agent_policy = resp.json()
            assigned_policy_id = agent_policy.get("policy_id")
            if assigned_policy_id == policy_id:
                print(f"  ✓ Agent correctly assigned to policy {policy_id}")
            else:
                print(f"  ⚠️  Agent assigned to policy {assigned_policy_id}, expected {policy_id}")
        except Exception as e:
            print(f"  ✗ Failed to verify agent policy: {e}")

        # 6. List controls
        await list_agent_controls(client, agent_uuid)

        # 7. Update the list control
        await update_control(client, list_control_id)

        # 8. Get updated control
        await get_control_data(client, list_control_id)

        # Summary
        print("\n" + "=" * 60)
        print("SETUP COMPLETE!")
        print("=" * 60)
        print(f"""
Controls created for agent '{AGENT_NAME}':

1. block-ssn-output (Regex)
   - Blocks SSN patterns like 123-45-6789 in OUTPUT
   - Check Stage: post (after function execution)

2. block-dangerous-sql (List)
   - Blocks dangerous SQL keywords in INPUT
   - Check Stage: pre (before function execution)
   - Keywords: DROP, DELETE, TRUNCATE, ALTER, GRANT, REVOKE, EXECUTE, SHUTDOWN, BACKUP

API Flow:
  Agent → Policy → Controls

Now run the agent demo:
  uv run python examples/agent_control_demo/demo_agent.py
""")


if __name__ == "__main__":
    asyncio.run(main())
