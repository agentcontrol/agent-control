#!/usr/bin/env python3
"""
Setup script that creates DeepEval-based controls for the Q&A Agent.

This script:
1. Registers the agent with the server
2. Creates DeepEval GEval evaluator controls for quality checks
3. Creates a policy and attaches controls
4. Assigns the policy to the agent

The controls demonstrate using DeepEval's LLM-as-a-judge to enforce:
- Response coherence
- Answer relevance
- Factual correctness

Run this after starting the server to have a working demo.
"""

import asyncio
import os
import sys
import uuid

import httpx

# Add the current directory to the path so we can import the evaluator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and register the DeepEval evaluator
# This must be done before creating controls that use it
try:
    from evaluator import DeepEvalEvaluator

    print(f"✓ DeepEval evaluator loaded: {DeepEvalEvaluator.metadata.name}")

    # Note: We don't check is_available() here because the evaluator
    # may not be used immediately - it just needs to be registered
    # so the server knows about it when creating control definitions

except ImportError as e:
    print(f"❌ Error: Cannot import DeepEval evaluator: {e}")
    print("\nMake sure you're running from the examples/deepeval directory")
    print("and that agent-control-models is installed")
    sys.exit(1)

# Agent configuration
AGENT_ID = "qa-agent-deepeval"
AGENT_NAME = "Q&A Agent with DeepEval"
AGENT_DESCRIPTION = "Question answering agent with DeepEval quality controls"

SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# DeepEval controls to create
DEEPEVAL_CONTROLS = [
    {
        "name": "check-coherence",
        "description": "Ensures LLM responses are coherent and logically consistent",
        "definition": {
            "description": "Ensures LLM responses are coherent and logically consistent",
            "enabled": True,
            "execution": "server",
            "scope": {"stages": ["post"]},
            "selector": {},
            "evaluator": {
                "name": "deepeval-geval",
                "config": {
                    "name": "Coherence",
                    "criteria": (
                        "Evaluate whether the response is coherent, logically consistent, "
                        "and well-structured. Check for contradictions and flow of ideas. "
                        "The response should make logical sense and not contain contradictory statements."
                    ),
                    "evaluation_params": ["input", "actual_output"],
                    "threshold": 0.6,
                    "model": "gpt-4o",
                    "strict_mode": False,
                    "verbose_mode": False,
                },
            },
            "action": {
                "decision": "deny",
                "message": "Response failed coherence check - please reformulate",
            },
        },
    },
    {
        "name": "check-relevance",
        "description": "Ensures responses are relevant to the user's question",
        "definition": {
            "description": "Ensures responses are relevant to the user's question",
            "enabled": True,
            "execution": "server",
            "scope": {"stages": ["post"]},
            "selector": {},
            "evaluator": {
                "name": "deepeval-geval",
                "config": {
                    "name": "Relevance",
                    "criteria": (
                        "Determine whether the actual output is relevant and directly addresses "
                        "the input query. Check if it stays on topic and provides useful information "
                        "that answers the question asked."
                    ),
                    "evaluation_params": ["input", "actual_output"],
                    "threshold": 0.5,
                    "model": "gpt-4o",
                    "strict_mode": False,
                },
            },
            "action": {
                "decision": "deny",
                "message": "Response is not relevant to the question - please provide a relevant answer",
            },
        },
    },
    {
        "name": "check-correctness",
        "description": "Validates factual correctness against expected answers (when available)",
        "definition": {
            "description": "Validates factual correctness against expected answers (when available)",
            "enabled": False,  # Disabled by default - enable when you have expected outputs
            "execution": "server",
            "scope": {"step_types": ["llm_inference"], "stages": ["post"]},
            "selector": {"path": "*"},
            "evaluator": {
                "name": "deepeval-geval",
                "config": {
                    "name": "Correctness",
                    "evaluation_steps": [
                        "Check whether facts in actual output contradict expected output",
                        "Heavily penalize omission of critical details",
                        "Minor wording differences are acceptable",
                        "Focus on factual accuracy, not style",
                    ],
                    "evaluation_params": ["actual_output", "expected_output"],
                    "threshold": 0.8,
                    "model": "gpt-4o",
                },
            },
            "action": {
                "decision": "warn",
                "message": "Response may contain factual errors - review carefully",
            },
        },
    },
]


async def setup_demo(quiet: bool = False):
    """Set up the demo agent with DeepEval controls."""
    # Generate the same UUID5 that the SDK generates
    agent_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID))

    print(f"Setting up agent: {AGENT_NAME}")
    print(f"Agent ID: {AGENT_ID}")
    print(f"Agent UUID: {agent_uuid}")
    print(f"Server URL: {SERVER_URL}")
    print()

    async with httpx.AsyncClient(base_url=SERVER_URL, timeout=30.0) as client:
        # Check server health
        try:
            resp = await client.get("/health")
            resp.raise_for_status()
            print("✓ Server is healthy")
        except httpx.HTTPError as e:
            print(f"❌ Error: Cannot connect to server at {SERVER_URL}")
            print(f"   {e}")
            print("\nMake sure the server is running")
            return False

        # Register the agent
        try:
            resp = await client.post(
                "/api/v1/agents/initAgent",
                json={
                    "agent": {
                        "agent_id": agent_uuid,
                        "agent_name": AGENT_NAME,
                        "agent_description": AGENT_DESCRIPTION,
                    },
                    "tools": [],
                },
            )
            resp.raise_for_status()
            result = resp.json()
            status = "Created" if result.get("created") else "Updated"
            print(f"✓ {status} agent: {AGENT_NAME}")
        except httpx.HTTPError as e:
            print(f"❌ Error registering agent: {e}")
            return False

        # Get or create a policy for the agent
        policy_name = f"policy-{AGENT_ID}"
        policy_id = None

        # Check if agent already has a policy
        try:
            resp = await client.get(f"/api/v1/agents/{agent_uuid}/policy")
            if resp.status_code == 200:
                policy_id = resp.json().get("policy_id")
                print(f"✓ Found existing policy: {policy_id}")
        except httpx.HTTPError:
            pass  # No policy yet

        # Create policy if needed
        if not policy_id:
            try:
                resp = await client.put(
                    "/api/v1/policies",
                    json={"name": policy_name},
                )
                if resp.status_code == 409:
                    # Policy name exists but not assigned - create with unique name
                    import time

                    policy_name = f"policy-{AGENT_ID}-{int(time.time())}"
                    resp = await client.put(
                        "/api/v1/policies",
                        json={"name": policy_name},
                    )
                resp.raise_for_status()
                policy_id = resp.json()["policy_id"]
                print(f"✓ Created policy: {policy_name}")

                # Assign policy to agent
                resp = await client.post(f"/api/v1/agents/{agent_uuid}/policy/{policy_id}")
                resp.raise_for_status()
                print(f"✓ Assigned policy to agent")
            except httpx.HTTPError as e:
                print(f"❌ Error setting up policy: {e}")
                return False

        # Create controls and add to policy
        print()
        print("Creating DeepEval controls...")
        controls_created = 0
        controls_updated = 0

        for control_spec in DEEPEVAL_CONTROLS:
            control_name = control_spec["name"]
            definition = control_spec["definition"]
            description = control_spec["description"]

            try:
                # Create control
                resp = await client.put(
                    "/api/v1/controls",
                    json={"name": control_name},
                )
                if resp.status_code == 409:
                    # Control exists, get its ID
                    resp = await client.get("/api/v1/controls", params={"name": control_name})
                    resp.raise_for_status()
                    controls = resp.json().get("controls", [])
                    if controls:
                        control_id = controls[0]["id"]
                        controls_updated += 1
                    else:
                        continue
                else:
                    resp.raise_for_status()
                    control_id = resp.json()["control_id"]
                    controls_created += 1

                # Set control definition
                resp = await client.put(
                    f"/api/v1/controls/{control_id}/data",
                    json={"data": definition},
                )
                resp.raise_for_status()

                # Add control to policy
                resp = await client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
                resp.raise_for_status()

                status = "✓" if definition.get("enabled") else "○"
                enabled_text = "enabled" if definition.get("enabled") else "disabled"
                print(f"  {status} {control_name} ({enabled_text})")
                print(f"     {description}")

            except httpx.HTTPError as e:
                print(f"  ❌ Error with control '{control_name}': {e}")
                continue

        print()
        if controls_created > 0:
            print(f"✓ Created {controls_created} new control(s)")
        if controls_updated > 0:
            print(f"✓ Updated {controls_updated} existing control(s)")
        print(f"✓ Agent has {len(DEEPEVAL_CONTROLS)} DeepEval control(s) configured")
        print()
        print("=" * 70)
        print("Setup Complete!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  1. Ensure OPENAI_API_KEY is set (required for DeepEval)")
        print("  2. Run the Q&A agent: python qa_agent.py")
        print("  3. Ask questions and observe quality controls in action")
        print()
        print("Note: The 'check-correctness' control is disabled by default.")
        print("      Enable it when you have test cases with expected outputs.")
        print()

        return True


if __name__ == "__main__":
    success = asyncio.run(setup_demo())
    sys.exit(0 if success else 1)
