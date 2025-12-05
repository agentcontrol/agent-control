#!/usr/bin/env python3
"""
Setup Luna2 controls and policy for the LangGraph agent.

This script creates:
- Luna2 controls (toxicity, prompt injection)
- Control set containing those controls
- Policy containing the control set
- Assigns the policy to the agent

Note: The agent DB entry itself is created automatically by agent_control.init()
when you run langgraph_with_controls.py. This script just ensures it exists
so we can assign a policy to it.

Prerequisites:
    1. Agent Control server running with Luna2 plugin:
       cd server && GALILEO_API_KEY="..." uv run uvicorn agent_control_server.main:app
    
    2. Galileo API configured for Luna2 evaluation

Usage:
    python setup_langgraph_controls.py
"""

import asyncio
import os
import sys
import uuid

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../sdks/python/src"))

from agent_control import AgentControlClient


# =============================================================================
# CONFIGURATION (must match langgraph_with_controls.py)
# =============================================================================

AGENT_NAME = "langgraph-safe-assistant"
AGENT_ID = "langgraph-safe-assistant-v1"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# Galileo project with Luna2 stage configured
GALILEO_PROJECT = os.getenv("GALILEO_PROJECT", "agent-control-demo")
LUNA2_STAGE = os.getenv("LUNA2_STAGE", "luna2-safety-stage")


# =============================================================================
# SETUP FUNCTIONS
# =============================================================================

def get_agent_uuid() -> str:
    """
    Get the deterministic UUID for the agent.
    
    Note: The agent DB entry is created automatically by agent_control.init()
    or by calling /initAgent. This just computes the same UUID.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID))


async def ensure_agent_exists(client: AgentControlClient) -> str:
    """
    Ensure agent exists in DB (idempotent via initAgent).
    
    initAgent creates the agent if it doesn't exist, or returns existing.
    This is the same endpoint that agent_control.init() calls.
    """
    agent_uuid = get_agent_uuid()
    
    try:
        response = await client.http_client.post(
            "/api/v1/agents/initAgent",
            json={
                "agent": {
                    "agent_id": agent_uuid,
                    "agent_name": AGENT_NAME,
                    "agent_description": "LangGraph agent with Luna2 safety controls",
                },
                "tools": []
            }
        )
        response.raise_for_status()
        data = response.json()
        
        status = "Created" if data.get("created") else "Found existing"
        print(f"✅ {status} agent: {AGENT_NAME} ({agent_uuid})")
        return agent_uuid
        
    except Exception as e:
        print(f"❌ Failed to ensure agent exists: {e}")
        raise


async def create_control(client: AgentControlClient, name: str, definition: dict) -> int:
    """Create a control with the given definition."""
    try:
        # Create control
        response = await client.http_client.put(
            "/api/v1/controls",
            json={"name": name}
        )
        
        if response.status_code == 409:
            print(f"ℹ️  Control '{name}' already exists")
            return -1
        
        response.raise_for_status()
        control_id = response.json().get("control_id")
        
        # Set control data
        response = await client.http_client.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": definition}
        )
        response.raise_for_status()
        
        print(f"✅ Created control: {name} (ID: {control_id})")
        return control_id
        
    except Exception as e:
        print(f"❌ Failed to create control '{name}': {e}")
        raise


async def create_luna2_toxicity_control(client: AgentControlClient) -> int:
    """Create Luna2 toxicity detection control."""
    print("\n📋 Creating Luna2 Toxicity Control...")
    
    definition = {
        "description": "Block toxic content using Luna2 toxicity detection",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "pre",  # Check INPUT before LLM call
        "selector": {"path": "input"},
        "evaluator": {
            "type": "plugin",
            "config": {
                "plugin_name": "luna2",
                "plugin_config": {
                    "stage_type": "central",
                    "stage_name": LUNA2_STAGE,
                    "galileo_project": GALILEO_PROJECT,
                    "metric": "input_toxicity",
                    "operator": ">",
                    "target_value": 0.5,
                    "fail_open": True,
                    "timeout_ms": 10000,
                }
            }
        },
        "action": {"decision": "deny"},
        "tags": ["luna2", "toxicity", "safety", "input"]
    }
    
    print(f"   Stage: {LUNA2_STAGE} (central)")
    print(f"   Metric: input_toxicity > 0.5")
    print(f"   Check: pre (before LLM)")
    
    return await create_control(client, "luna2-toxicity-input", definition)


async def create_luna2_prompt_injection_control(client: AgentControlClient) -> int:
    """Create Luna2 prompt injection detection control."""
    print("\n📋 Creating Luna2 Prompt Injection Control...")
    
    definition = {
        "description": "Block prompt injection attempts using Luna2",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "pre",  # Check INPUT before LLM call
        "selector": {"path": "input"},
        "evaluator": {
            "type": "plugin",
            "config": {
                "plugin_name": "luna2",
                "plugin_config": {
                    "stage_type": "central",
                    "stage_name": LUNA2_STAGE,
                    "galileo_project": GALILEO_PROJECT,
                    "metric": "prompt_injection",
                    "operator": ">",
                    "target_value": 0.5,
                    "fail_open": True,
                    "timeout_ms": 10000,
                }
            }
        },
        "action": {"decision": "deny"},
        "tags": ["luna2", "prompt-injection", "safety", "input"]
    }
    
    print(f"   Stage: {LUNA2_STAGE} (central)")
    print(f"   Metric: prompt_injection > 0.5")
    print(f"   Check: pre (before LLM)")
    
    return await create_control(client, "luna2-prompt-injection", definition)


async def create_luna2_output_toxicity_control(client: AgentControlClient) -> int:
    """Create Luna2 output toxicity detection control."""
    print("\n📋 Creating Luna2 Output Toxicity Control...")
    
    definition = {
        "description": "Block toxic LLM outputs using Luna2",
        "enabled": True,
        "applies_to": "llm_call",
        "check_stage": "post",  # Check OUTPUT after LLM call
        "selector": {"path": "output"},
        "evaluator": {
            "type": "plugin",
            "config": {
                "plugin_name": "luna2",
                "plugin_config": {
                    "stage_type": "central",
                    "stage_name": LUNA2_STAGE,
                    "galileo_project": GALILEO_PROJECT,
                    "metric": "output_toxicity",
                    "operator": ">",
                    "target_value": 0.5,
                    "fail_open": True,
                    "timeout_ms": 10000,
                }
            }
        },
        "action": {"decision": "deny"},
        "tags": ["luna2", "toxicity", "safety", "output"]
    }
    
    print(f"   Stage: {LUNA2_STAGE} (central)")
    print(f"   Metric: output_toxicity > 0.5")
    print(f"   Check: post (after LLM)")
    
    return await create_control(client, "luna2-toxicity-output", definition)


async def create_control_set(client: AgentControlClient, name: str) -> int:
    """Create a control set."""
    try:
        response = await client.http_client.put(
            "/api/v1/control-sets",
            json={"name": name}
        )
        
        if response.status_code == 409:
            print(f"ℹ️  Control set '{name}' already exists")
            return -1
        
        response.raise_for_status()
        control_set_id = response.json().get("control_set_id")
        
        print(f"✅ Created control set: {name} (ID: {control_set_id})")
        return control_set_id
        
    except Exception as e:
        print(f"❌ Failed to create control set: {e}")
        raise


async def create_policy(client: AgentControlClient, name: str) -> int:
    """Create a policy."""
    try:
        response = await client.http_client.put(
            "/api/v1/policies",
            json={"name": name}
        )
        
        if response.status_code == 409:
            print(f"ℹ️  Policy '{name}' already exists")
            return -1
        
        response.raise_for_status()
        policy_id = response.json().get("policy_id")
        
        print(f"✅ Created policy: {name} (ID: {policy_id})")
        return policy_id
        
    except Exception as e:
        print(f"❌ Failed to create policy: {e}")
        raise


async def main():
    """Set up Luna2 controls for LangGraph agent."""
    print("=" * 70)
    print("🔧 SETUP: Luna2 Controls for LangGraph Agent")
    print("=" * 70)
    print(f"\nServer: {SERVER_URL}")
    print(f"Agent: {AGENT_NAME}")
    print(f"Galileo Project: {GALILEO_PROJECT}")
    print(f"Luna2 Stage: {LUNA2_STAGE}")
    
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # Check server
        try:
            health = await client.health_check()
            print(f"\n✅ Server healthy: {health.get('status')}")
        except Exception as e:
            print(f"\n❌ Server not available: {e}")
            print("\nStart the server first:")
            print("  cd server && GALILEO_API_KEY='...' uv run uvicorn agent_control_server.main:app")
            return
        
        # 1. Ensure agent exists (initAgent is idempotent)
        print("\n" + "=" * 70)
        print("STEP 1: Ensure Agent Exists")
        print("=" * 70)
        agent_uuid = await ensure_agent_exists(client)
        
        # 2. Create controls
        print("\n" + "=" * 70)
        print("STEP 2: Create Luna2 Controls")
        print("=" * 70)
        
        toxicity_id = await create_luna2_toxicity_control(client)
        injection_id = await create_luna2_prompt_injection_control(client)
        output_toxicity_id = await create_luna2_output_toxicity_control(client)
        
        # Check if any controls existed
        control_ids = [toxicity_id, injection_id, output_toxicity_id]
        if -1 in control_ids:
            print("\n⚠️  Some controls already exist. Skipping remaining setup.")
            print("   Delete existing controls to re-run full setup.")
            return
        
        # 3. Create control set
        print("\n" + "=" * 70)
        print("STEP 3: Create Control Set")
        print("=" * 70)
        
        control_set_id = await create_control_set(client, "langgraph-luna2-controls")
        if control_set_id == -1:
            print("\n⚠️  Control set exists. Skipping.")
            return
        
        # Add controls to set
        for ctrl_id in control_ids:
            await client.http_client.post(
                f"/api/v1/control-sets/{control_set_id}/controls/{ctrl_id}"
            )
        print(f"   Added {len(control_ids)} controls to set")
        
        # 4. Create policy
        print("\n" + "=" * 70)
        print("STEP 4: Create Policy")
        print("=" * 70)
        
        policy_id = await create_policy(client, "langgraph-luna2-policy")
        if policy_id == -1:
            print("\n⚠️  Policy exists. Skipping.")
            return
        
        # Add control set to policy
        await client.http_client.post(
            f"/api/v1/policies/{policy_id}/control_sets/{control_set_id}"
        )
        print(f"   Added control set to policy")
        
        # 5. Assign policy to agent
        print("\n" + "=" * 70)
        print("STEP 5: Assign Policy to Agent")
        print("=" * 70)
        
        await client.http_client.post(
            f"/api/v1/agents/{agent_uuid}/policy/{policy_id}"
        )
        print(f"✅ Assigned policy to agent")
        
        # Summary
        print("\n" + "=" * 70)
        print("🎉 SETUP COMPLETE!")
        print("=" * 70)
        print(f"""
Agent: {AGENT_NAME}
  UUID: {agent_uuid}
  
Policy: langgraph-luna2-policy
  └── Control Set: langgraph-luna2-controls
      ├── luna2-toxicity-input (pre-check)
      ├── luna2-prompt-injection (pre-check)
      └── luna2-toxicity-output (post-check)

Now run the LangGraph agent:
  python langgraph_with_controls.py
""")


if __name__ == "__main__":
    asyncio.run(main())

