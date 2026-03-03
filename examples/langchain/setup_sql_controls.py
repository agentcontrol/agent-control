"""
Setup script for SQL agent controls.

This script creates the SQL control and associates it directly to the agent.
Run this once before running sql_agent_protection.py.

NOTE: This script is designed to run once. If resources already exist,
you may need to either:
  - Delete them from the server first
  - Manually note their IDs for use in the agent code
"""

import asyncio
import os
import pathlib

import requests

from agent_control import Agent, AgentControlClient, agents, controls

AGENT_ID = "edf66504-0db5-4ee8-9e09-3ef37bbb8faa"
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
    """Create SQL control and associate it directly with the agent."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register Agent
        agent_name = AGENT_ID
        
        agent = Agent(
            agent_name=agent_name,
            agent_description="SQL agent with server-side controls"
        )
        
        try:
            await agents.register_agent(client, agent, steps=[])
            print(f"✓ Agent registered: {AGENT_ID}")
        except Exception as e:
            print(f"ℹ️  Agent might already exist: {e}")

        # 2. Create SQL Control
        sql_control_data = {
            "description": "Prevent dangerous SQL operations",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["sql_db_query"],
                "stages": ["pre"]
            },
            "selector": {
                "path": "input.query"
            },
            "evaluator": {
                "name": "sql",
                "config": {
                    "blocked_operations": ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT"],
                    "allow_multi_statements": False,
                    "require_limit": True,
                    "max_limit": 100
                }
            },
            "action": {"decision": "deny"}
        }

        # Client-side control example (SDK execution)
        # To run controls locally, set "execution": "sdk" and use
        # agent_control.check_evaluation_with_local(...) in your agent code.
        sql_control_data_sdk = {
            **sql_control_data,
            "execution": "sdk",
        }

        try:
            control_result = await controls.create_control(
                client,
                name="sql-safety-tool-call",
                data=sql_control_data,
            )
            control_id = control_result["control_id"]
            print(f"✓ SQL Control created (ID: {control_id})")
        except Exception as e:
            if "409" in str(e):
                # Control exists - try to find it
                print("ℹ️  SQL Control 'sql-safety-tool-call' already exists, looking it up...")
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

        # Ensure control has valid data (older runs may have created it empty/corrupt)
        control_details = await controls.get_control(client, control_id)
        if not control_details.get("data"):
            print("ℹ️  Control has no valid data, updating configuration...")
            await controls.set_control_data(client, control_id, sql_control_data)
            print("✓ Control configuration updated")
        
        # 3. Associate control directly with agent
        try:
            await agents.add_agent_control(client, agent_name, control_id)
            print("✓ Associated control directly with agent")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print("ℹ️  Control already associated with agent (OK)")
            else:
                print(f"❌ Failed to associate control with agent: {e}")
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
    
    # Step 2: Setup controls and direct agent associations
    asyncio.run(setup_sql_controls())
