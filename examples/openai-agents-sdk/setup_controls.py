"""
Setup script for openai-agents SDK example with three-layer SSN protection.

This script creates:
1. An agent registration
2. Three SSN protection controls (pre-LLM, pre-tool, post-tool)
3. A policy that applies all three controls
4. Assignment of the policy to the agent

Run this ONCE before running the agent example:
    $ uv run setup_controls.py
"""

import asyncio
import os

import agent_control
from agent_control import AgentControlClient, controls, policies


# Agent configuration
AGENT_ID = "openai-agents-sdk-demo-v1"
AGENT_NAME = "openai-agents SDK Demo"
SERVER_URL = os.getenv("AGENT_CONTROL_SERVER_URL", "http://localhost:8000")

# Initialize agent (this registers it with the server)
agent_control.init(
    agent_name=AGENT_NAME,
    agent_id=AGENT_ID,
    agent_description="Demo agent with protected tools using openai-agents SDK",
    server_url=SERVER_URL,
)

# SSN regex pattern
SSN_PATTERN = r"\b\d{3}-\d{2}-\d{4}\b"

# Three-layer control definitions
CONTROL_DEFINITIONS = [
    {
        "name": "block-ssn-in-input",
        "description": "Block SSN patterns in user input before sending to LLM",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["llm_inference"],
            "stages": ["pre"],
        },
        "selector": {"path": "input"},
        "evaluator": {
            "plugin": "regex",
            "config": {
                "pattern": SSN_PATTERN,
                "description": "Detects SSN patterns (XXX-XX-XXXX)",
            },
        },
        "action": {"decision": "deny"},
    },
    {
        "name": "block-ssn-field-access",
        "description": "Block tool calls that try to access SSN field",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["tool"],
            "step_names": ["get_user_data"],
            "stages": ["pre"],
        },
        "selector": {
            "path": "input.fields",
        },
        "evaluator": {
            "plugin": "list",
            "config": {
                "values": ["ssn"],  # List plugin uses "values", not "contains"
                "case_sensitive": False,
            },
        },
        "action": {"decision": "deny"},
    },
    {
        "name": "block-ssn-in-tool-output",
        "description": "Block tool outputs containing SSN patterns (defense in depth)",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["tool"],
            "step_names": ["get_user_data"],
            "stages": ["post"],
        },
        "selector": {
            "path": "output",
        },
        "evaluator": {
            "plugin": "regex",
            "config": {
                "pattern": SSN_PATTERN,
                "description": "Detects SSN patterns in tool output",
            },
        },
        "action": {"decision": "deny"},
    },
]


async def create_or_get_control(
    client: AgentControlClient, control_def: dict
) -> str:
    """Create a control or return existing control ID."""
    name = control_def["name"]
    data = {k: v for k, v in control_def.items() if k != "name"}
    data["enabled"] = True
    
    try:
        result = await controls.create_control(client, name=name, data=data)
        control_id = result["control_id"]
        print(f"✓ Control created: {name} (ID: {control_id})")
        return control_id
    except Exception as e:
        if "409" in str(e):
            print(f"ℹ️  Control '{name}' already exists, looking it up...")
            controls_list = await controls.list_controls(client, name=name, limit=1)
            if controls_list["controls"]:
                control_id = controls_list["controls"][0]["id"]
                print(f"ℹ️  Using existing control (ID: {control_id})")
                return control_id
            else:
                print(f"❌ Could not find existing control '{name}'")
                raise SystemExit(1)
        else:
            # Print the control data for debugging
            import json
            print(f"\n❌ Error creating control '{name}':")
            print(f"Error: {e}")
            print(f"\nControl data sent:")
            print(json.dumps(data, indent=2))
            raise


async def setup_controls():
    """Setup agent, tool controls, and policy."""
    print("=" * 60)
    print("Setting up Agent Control for openai-agents SDK")
    print("=" * 60)
    print(f"\nServer URL: {SERVER_URL}")
    print(f"Agent ID: {AGENT_ID}\n")
    
    # Get the agent UUID from the initialized agent
    agent = agent_control.current_agent()
    if not agent:
        print("❌ Error: Agent not initialized. agent_control.init() should have run.")
        raise SystemExit(1)
    
    agent_uuid = agent.agent_id
    print(f"✓ Agent already registered via agent_control.init()")
    print(f"  Agent UUID: {agent_uuid}\n")
    
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Create three SSN protection controls
        print(f"\n🔒 Step 1: Creating three-layer SSN protection...")
        control_ids = []
        for idx, control_def in enumerate(CONTROL_DEFINITIONS, 1):
            print(f"\n  Layer {idx}: {control_def['description']}")
            control_id = await create_or_get_control(client, control_def)
            control_ids.append(control_id)
        
        # 2. Create Policy
        print(f"\n📋 Step 2: Creating policy...")
        try:
            policy_result = await policies.create_policy(
                client, name="openai-agents-policy"
            )
            policy_id = policy_result["policy_id"]
            print(f"✓ Policy created (ID: {policy_id})")
        except Exception as e:
            if "409" in str(e):
                print(f"⚠️  Policy 'openai-agents-policy' already exists.")
                print("    Cannot proceed - SDK doesn't support looking up policies by name.")
                print("\n    To fix this, delete the existing policy:")
                print(f"       curl -X DELETE {SERVER_URL}/api/v1/policies/<policy_id>")
                print("    Or use a different policy name in this script.")
                raise SystemExit(1)
            else:
                raise
        
        # 3. Add all controls to policy
        print(f"\n🔗 Step 3: Adding controls to policy...")
        for idx, control_id in enumerate(control_ids, 1):
            try:
                await policies.add_control_to_policy(client, policy_id, control_id)
                print(f"✓ Layer {idx} control added to policy")
            except Exception as e:
                print(f"⚠️  Adding control {idx}: {e}")
        
        # 4. Assign policy to agent
        print(f"\n🎯 Step 4: Assigning policy to agent...")
        try:
            await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
            print(f"✓ Policy assigned to agent")
        except Exception as e:
            print(f"⚠️  Assigning policy to agent: {e}")
        
        print("\n" + "=" * 60)
        print("✅ Setup Complete!")
        print("=" * 60)
        print("\nRun the agent example:")
        print("  $ uv run user_data_agent_protection.py")
        print("\nThree-layer SSN protection:")
        print("  1. Pre-LLM: Blocks SSN patterns in user input")
        print("  2. Pre-Tool: Blocks tool calls requesting SSN field")
        print("  3. Post-Tool: Blocks SSN patterns in tool output (defense in depth)")


if __name__ == "__main__":
    asyncio.run(setup_controls())
