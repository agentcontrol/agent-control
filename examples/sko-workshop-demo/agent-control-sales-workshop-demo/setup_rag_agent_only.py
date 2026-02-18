#!/usr/bin/env python3
"""Register ONLY the RAG agent and assign a policy (no controls).

This lets you create controls from scratch in the UI.
"""

import asyncio
import os
import sys
from uuid import UUID

SDK_FALLBACK = "/Users/namrataghadi/code/agentcontrol/agent-control/sdks/python/src"
if SDK_FALLBACK not in sys.path:
    sys.path.insert(0, SDK_FALLBACK)

from agent_control import Agent, AgentControlClient, agents, policies

AGENT_NAME = "RAG Q&A Agent"
AGENT_ID = "9e9a1c8e-8c3f-4c6d-9d2a-0d3d5e8a1b77"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
POLICY_NAME = "rag-demo-policy"


async def main() -> None:
    print("=" * 70)
    print("AgentControl RAG Demo - Register Agent + Policy Only")
    print("=" * 70)
    print(f"Server: {SERVER_URL}")

    async with AgentControlClient(base_url=SERVER_URL) as client:
        try:
            await client.health_check()
            print("✓ Server healthy")
        except Exception as e:
            print(f"✗ Server not reachable: {e}")
            print("Start server: cd server && make run")
            return

        agent = Agent(
            agent_id=UUID(AGENT_ID),
            agent_name=AGENT_NAME,
            agent_description="RAG Q&A demo agent",
        )
        await agents.register_agent(client, agent, steps=[])
        print(f"✓ Agent registered: {AGENT_NAME}")

        # Create or reuse policy, then assign to agent
        policy_id = None
        try:
            result = await policies.create_policy(client, POLICY_NAME)
            policy_id = result["policy_id"]
            print(f"✓ Policy created: {POLICY_NAME} (ID {policy_id})")
        except Exception as e:
            if "409" in str(e):
                try:
                    policy_info = await agents.get_agent_policy(client, AGENT_ID)
                    policy_id = policy_info.get("policy_id")
                    print(f"✓ Using existing policy ID: {policy_id}")
                except Exception:
                    import time
                    alt_name = f"{POLICY_NAME}-{int(time.time())}"
                    result = await policies.create_policy(client, alt_name)
                    policy_id = result["policy_id"]
                    print(f"✓ Policy created: {alt_name} (ID {policy_id})")
            else:
                raise

        await policies.assign_policy_to_agent(client, AGENT_ID, policy_id)
        print("✓ Policy assigned to agent")
        print("No controls were created. Create controls in the UI.")


if __name__ == "__main__":
    asyncio.run(main())
