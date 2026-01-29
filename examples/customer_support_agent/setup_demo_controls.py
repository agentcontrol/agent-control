#!/usr/bin/env python3
"""
Setup script that creates demo controls for the Customer Support Agent.

This script:
1. Registers the agent with the server
2. Creates demo controls (PII detection, prompt injection)
3. Creates a policy and attaches controls
4. Assigns the policy to the agent

Run this after starting the server to have a working demo out of the box.
"""

import asyncio
import os
import uuid

from agent_control import Agent, AgentControlClient, agents, controls, policies

# Same agent ID as in support_agent.py
AGENT_ID = "customer-support-agent"
AGENT_NAME = "Customer Support Agent"
AGENT_DESCRIPTION = "AI-powered customer support assistant"

SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# Demo controls to create
# Demonstrates various ControlSelector options: path, tool_names, tool_name_regex
DEMO_CONTROLS = [
    # ==========================================================================
    # LLM CALL CONTROLS (using 'path' selector)
    # ==========================================================================
    {
        "name": "block-ssn-in-output",
        "description": "Blocks responses containing SSN patterns (path: output)",
        "definition": {
            "description": "Blocks responses containing SSN patterns (path: output)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm_inference"], "stages": ["post"]},
            "selector": {"path": "output"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": r"\d{3}-\d{2}-\d{4}"},
            },
            "action": {
                "decision": "deny",
                "message": "Response contains SSN pattern - blocked for PII protection",
            },
        },
    },
    {
        "name": "block-prompt-injection",
        "description": "Blocks common prompt injection attempts (path: input)",
        "definition": {
            "description": "Blocks common prompt injection attempts (path: input)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm_inference"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(?i)(ignore.{0,20}(previous|prior|above).{0,20}instructions|you are now|system:|forget everything|disregard)"
                },
            },
            "action": {
                "decision": "deny",
                "message": "Potential prompt injection detected - request blocked",
            },
        },
    },
    {
        "name": "block-credit-card",
        "description": "Blocks messages containing credit card numbers (path: input)",
        "definition": {
            "description": "Blocks messages containing credit card numbers (path: input)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm_inference"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"},
            },
            "action": {
                "decision": "deny",
                "message": "Credit card number detected - please don't share payment info",
            },
        },
    },
    # ==========================================================================
    # TOOL CALL CONTROLS - using 'tool_names' (exact match)
    # ==========================================================================
    {
        "name": "block-sql-injection-customer-lookup",
        "description": "Blocks SQL injection in customer lookup (tool_names: exact match)",
        "definition": {
            "description": "Blocks SQL injection in customer lookup (tool_names: exact match)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {
                "path": "input.query",
                "tool_names": ["lookup_customer"],  # Only applies to this exact tool
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": r"(?i)(select|insert|update|delete|drop|union|--|;)"
                },
            },
            "action": {
                "decision": "deny",
                "message": "Potential SQL injection in customer lookup query",
            },
        },
    },
    {
        "name": "log-ticket-creation",
        "description": "Logs all ticket creation for audit (tool_names: exact match)",
        "definition": {
            "description": "Logs all ticket creation for audit (tool_names: exact match)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {
                "path": "*",  # Log entire payload
                "tool_names": ["create_ticket"],
            },
            "evaluator": {
                "name": "regex",
                "config": {"pattern": r".*"},  # Always matches
            },
            "action": {
                "decision": "log",
                "message": "Ticket creation logged for audit",
            },
        },
    },
    # ==========================================================================
    # TOOL CALL CONTROLS - using 'tool_name_regex' (pattern match)
    # ==========================================================================
    {
        "name": "block-profanity-in-search",
        "description": "Blocks profanity in any search/lookup tool (tool_name_regex: pattern)",
        "definition": {
            "description": "Blocks profanity in any search/lookup tool (tool_name_regex: pattern)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {
                "path": "input.query",
                # Applies to any tool containing 'search' or 'lookup'
                "tool_name_regex": r"(search|lookup)",
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    # Simple profanity pattern for demo
                    "pattern": r"(?i)\b(badword|offensive|inappropriate)\b"
                },
            },
            "action": {
                "decision": "deny",
                "message": "Inappropriate content detected in search query",
            },
        },
    },
    {
        "name": "warn-high-priority-ticket",
        "description": "Warns on high priority tickets (path: arguments.priority)",
        "definition": {
            "description": "Warns on high priority tickets (path: input.priority)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {
                "path": "input.priority",
                "tool_name_regex": r".*ticket.*",  # Any tool with 'ticket' in name
            },
            "evaluator": {
                "name": "list",
                "config": {
                    "values": ["high", "critical", "urgent"],
                    "logic": "any",
                    "match_on": "match",
                    "match_mode": "exact",
                    "case_sensitive": False,
                },
            },
            "action": {
                "decision": "warn",
                "message": "High priority ticket requires manager approval",
            },
        },
    },
    # ==========================================================================
    # TOOL CALL CONTROLS - using 'path' with nested arguments
    # ==========================================================================
    {
        "name": "block-pii-in-ticket-description",
        "description": "Blocks PII in ticket descriptions (path: arguments.description)",
        "definition": {
            "description": "Blocks PII in ticket descriptions (path: input.description)",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "selector": {
                "path": "input.description",
                "tool_names": ["create_ticket"],
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    # Email pattern
                    "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                },
            },
            "action": {
                "decision": "warn",
                "message": "Email address detected in ticket - consider removing PII",
            },
        },
    },
]


async def setup_demo(quiet: bool = False):
    """Set up the demo agent with controls."""
    # Generate the same UUID5 that the SDK generates
    agent_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID))

    async with AgentControlClient(base_url=SERVER_URL, timeout=30.0) as client:
        # Check server health
        try:
            await client.health_check()
        except Exception as e:
            print(f"Error: Cannot connect to server at {SERVER_URL}")
            print(f"  {e}")
            print("\nMake sure the server is running: ./demo.sh start")
            return False

        # Register the agent
        try:
            agent = Agent(
                agent_id=agent_uuid,
                agent_name=AGENT_NAME,
                agent_description=AGENT_DESCRIPTION,
            )
            result = await agents.register_agent(client, agent, steps=[])
            status = "Created" if result.get("created") else "Updated"
            print(f"  {status} agent: {AGENT_NAME}")
        except Exception as e:
            print(f"  Error registering agent: {e}")
            return False

        # Get or create a policy for the agent
        policy_name = f"policy-{AGENT_ID}"
        policy_id = None

        # Check if agent already has a policy
        try:
            policy_info = await agents.get_agent_policy(client, agent_uuid)
            policy_id = policy_info.get("policy_id")
        except Exception:
            policy_id = None  # No policy yet

        # Create policy if needed
        if not policy_id:
            try:
                policy_result = await policies.create_policy(client, policy_name)
                policy_id = policy_result["policy_id"]
                print(f"  Created policy: {policy_name}")
            except Exception as e:
                if "409" in str(e):
                    import time
                    policy_name = f"policy-{AGENT_ID}-{int(time.time())}"
                    policy_result = await policies.create_policy(client, policy_name)
                    policy_id = policy_result["policy_id"]
                    print(f"  Created policy: {policy_name}")
                else:
                    print(f"  Error setting up policy: {e}")
                    return False

            try:
                await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
            except Exception as e:
                print(f"  Error assigning policy: {e}")
                return False

        # Create controls and add to policy
        controls_created = 0
        for control_spec in DEMO_CONTROLS:
            control_name = control_spec["name"]
            definition = control_spec["definition"]

            try:
                control_result = await controls.create_control(
                    client, name=control_name, data=definition
                )
                control_id = control_result["control_id"]
                if control_result.get("configured"):
                    controls_created += 1
            except Exception as e:
                if "409" in str(e):
                    control_list = await controls.list_controls(client, name=control_name, limit=1)
                    existing = control_list.get("controls", [])
                    if not existing:
                        continue
                    control_id = existing[0]["id"]
                    await controls.set_control_data(client, control_id, definition)
                else:
                    print(f"  Error with control '{control_name}': {e}")
                    continue

            try:
                await policies.add_control_to_policy(client, policy_id, control_id)
            except Exception as e:
                print(f"  Error adding control '{control_name}' to policy: {e}")
                continue

        if controls_created > 0:
            print(f"  Created {controls_created} control(s)")
        print(f"  Agent has {len(DEMO_CONTROLS)} demo control(s) configured")

        return True


if __name__ == "__main__":
    success = asyncio.run(setup_demo())
    exit(0 if success else 1)
