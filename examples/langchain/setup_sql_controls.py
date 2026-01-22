"""
Setup script for SQL agent controls.

This script creates the SQL control and policy on the server.
Run this once before running sql_agent_protection.py.

NOTE: This script is designed to run once. If resources already exist,
you may need to either:
  - Delete them from the server first
  - Manually note their IDs for use in the agent code
"""

import asyncio
import os
import pathlib
import uuid

import requests

from agent_control import Agent, AgentControlClient, agents, controls, policies

AGENT_ID = "sql-agent-demo"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


def setup_database():
    """Download and setup a fresh Chinook database."""
    url = "https://storage.googleapis.com/benchmarks-artifacts/chinook/Chinook.db"
    local_path = pathlib.Path("Chinook.db")
    
    # Always download fresh database for setup
    print("📥 Downloading fresh Chinook database...")
    response = requests.get(url)
    if response.status_code == 200:
        local_path.write_bytes(response.content)
        print("✓ Database downloaded successfully")
    else:
        raise Exception(f"Failed to download database: {response.status_code}")
    
    # Verify the Artist table exists
    import sqlite3
    conn = sqlite3.connect(str(local_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM Artist")
    count = cursor.fetchone()[0]
    conn.close()
    
    print(f"✓ Database verified: {count} artists in Artist table")


async def setup_sql_controls():
    """Create SQL control, policy, and assign to agent."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register Agent
        agent_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID)
        
        agent = Agent(
            agent_id=agent_uuid,
            agent_name="SQL Demo Agent",
            agent_description="SQL agent with server-side controls"
        )
        
        try:
            await agents.register_agent(client, agent, tools=[])
            print(f"✓ Agent registered: {AGENT_ID}")
        except Exception as e:
            print(f"ℹ️  Agent might already exist: {e}")

        # 2. Create SQL Control
        sql_control_data = {
            "description": "Prevent dangerous SQL operations",
            "enabled": True,
            "applies_to": "tool_call",
            "check_stage": "pre",
            "selector": {
                "path": "arguments.query",
                "tool_names": ["sql_db_query"]
            },
            "evaluator": {
                "plugin": "sql",
                "config": {
                    "blocked_operations": ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT"],
                    "allow_multi_statements": False,
                    "require_limit": True,
                    "max_limit": 100
                }
            },
            "action": {"decision": "deny"}
        }

        try:
            control_result = await controls.create_control(
                client, 
                name="sql-safety-tool-call", 
                data=sql_control_data
            )
            control_id = control_result["control_id"]
            print(f"✓ SQL Control created (ID: {control_id})")
        except Exception as e:
            if "409" in str(e):
                # Control exists - try to find it
                print(f"ℹ️  SQL Control 'sql-safety-tool-call' already exists, looking it up...")
                controls_list = await controls.list_controls(
                    client, name="sql-safety-tool-call", limit=1
                )
                if controls_list["controls"]:
                    control_id = controls_list["controls"][0]["id"]
                    print(f"ℹ️  Using existing control (ID: {control_id})")
                else:
                    print("❌ Could not find existing control 'sql-safety-tool-call'")
                    raise SystemExit(1)
            else:
                raise
        
        # 3. Create Policy
        try:
            policy_result = await policies.create_policy(
                client, name="sql-protection-policy"
            )
            policy_id = policy_result["policy_id"]
            print(f"✓ Policy created (ID: {policy_id})")
        except Exception as e:
            if "409" in str(e):
                print(f"⚠️  Policy 'sql-protection-policy' already exists.")
                print("    Cannot proceed - SDK doesn't support looking up policies by name.")
                print("\n    To fix this, run one of these commands:")
                print("    1. Delete via server API:")
                print(f"       curl -X DELETE {SERVER_URL}/api/v1/policies/<policy_id>")
                print("    2. Or use the server UI to delete the policy")
                print("\n    Then re-run this script.")
                raise SystemExit(1)
            raise
        
        # 4. Add Control to Policy
        try:
            await policies.add_control_to_policy(client, policy_id, control_id)
            print(f"✓ Added control to policy")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print(f"ℹ️  Control already in policy (OK)")
            else:
                print(f"❌ Failed to add control to policy: {e}")
                raise
        
        # 5. Assign Policy to Agent
        try:
            await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
            print(f"✓ Assigned policy to agent")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print(f"ℹ️  Policy already assigned to agent (OK)")
            else:
                print(f"❌ Failed to assign policy: {e}")
                raise
        
        print("\n✅ Setup complete! You can now run sql_agent_protection.py")


if __name__ == "__main__":
    print("=" * 60)
    print("SQL Agent Control Setup")
    print("=" * 60)
    print()
    
    # Step 1: Setup fresh database
    setup_database()
    print()
    
    # Step 2: Setup controls and policies
    asyncio.run(setup_sql_controls())

