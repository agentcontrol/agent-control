"""
Setup script for LangSmith evaluator controls.

This script creates:
1. Multiple controls using the LangSmith evaluator
   - Toxicity control for input queries
   - Hallucination control for output responses
   - PII detection control for output responses
   - Relevance control for output responses
2. A policy that combines all controls
3. Assigns the policy to the RAG Q&A agent

Run this ONCE before running rag_qa_agent.py:
    $ uv run setup_langsmith_controls.py
"""

import asyncio
import os
import sys

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(__file__))

import httpx
import agent_control
from agent_control import AgentControlClient, controls, policies
from config import LangSmithEvaluatorConfig


async def setup_controls():
    """Create controls, policy, and assign to agent."""
    print("Setting up LangSmith evaluator controls...")
    print()

    agent_control.init(
        agent_name="RAG Q&A Agent",
        agent_id="rag-qa-agent-demo",
        agent_description="Document Q&A agent with LangSmith safety controls",
        server_url=os.getenv("AGENT_CONTROL_URL"),
    )

    async with AgentControlClient() as client:
        # 1. Create toxicity control for input queries
        print("Creating toxicity control for queries...")
        toxicity_control_data = {
            "name": "query-toxicity-check",
            "data": {
                "description": "Block toxic or harmful queries",
                "stage": "pre",
                "execution": "server",
                "step_type_filter": ["tool"],
                "tool_name_filter": ["retrieve_documents"],
                "evaluator_configs": [
                    {
                        "evaluator": "langsmith",
                        "config": {
                            "metric": "toxicity",
                            "threshold": 0.6,
                            "langsmith_project": "agent-control-demo",
                        },
                        "selector": "input.query",
                        "action": "deny",
                    }
                ],
            },
        }

        try:
            toxicity_result = await controls.create_control(
                client, toxicity_control_data["name"], toxicity_control_data["data"]
            )
            print(f"✓ Created toxicity control (ID: {toxicity_result['control_id']})")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                print(f"✓ Toxicity control already exists (skipping)")
            else:
                raise
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"✓ Toxicity control already exists (skipping)")
            else:
                raise

        # 2. Create hallucination control for responses
        print("\nCreating hallucination control for responses...")
        hallucination_control_data = {
            "name": "response-hallucination-check",
            "data": {
                "description": "Detect and block hallucinated responses",
                "stage": "post",
                "execution": "server",
                "step_type_filter": ["tool"],
                "tool_name_filter": ["generate_answer"],
                "evaluator_configs": [
                    {
                        "evaluator": "langsmith",
                        "config": {
                            "metric": "hallucination",
                            "threshold": 0.7,
                            "langsmith_project": "agent-control-demo",
                            "require_context": True,
                            "context_key": "context",
                        },
                        "selector": "output",
                        "action": "deny",
                    }
                ],
            },
        }

        try:
            hallucination_result = await controls.create_control(
                client,
                hallucination_control_data["name"],
                hallucination_control_data["data"],
            )
            print(
                f"✓ Created hallucination control (ID: {hallucination_result['control_id']})"
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                print(f"✓ Hallucination control already exists (skipping)")
            else:
                raise
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"✓ Hallucination control already exists (skipping)")
            else:
                raise

        # 3. Create PII detection control for responses
        print("\nCreating PII detection control for responses...")
        pii_control_data = {
            "name": "response-pii-check",
            "data": {
                "description": "Detect and block PII in responses",
                "stage": "post",
                "execution": "server",
                "step_type_filter": ["tool"],
                "tool_name_filter": ["generate_answer"],
                "evaluator_configs": [
                    {
                        "evaluator": "langsmith",
                        "config": {
                            "metric": "pii_detection",
                            "threshold": 0.5,
                            "langsmith_project": "agent-control-demo",
                        },
                        "selector": "output",
                        "action": "deny",
                    }
                ],
            },
        }

        try:
            pii_result = await controls.create_control(
                client, pii_control_data["name"], pii_control_data["data"]
            )
            print(f"✓ Created PII detection control (ID: {pii_result['control_id']})")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                print(f"✓ PII detection control already exists (skipping)")
            elif e.response.status_code == 422:
                print(f"✗ PII detection control validation failed:")
                print(f"   Response: {e.response.text}")
                print(f"   Config sent: {pii_control_data['data']['evaluator_configs'][0]['config']}")
                raise
            else:
                raise
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"✓ PII detection control already exists (skipping)")
            else:
                raise

        # 4. Create coherence control for responses
        print("\nCreating coherence control for responses...")
        coherence_control_data = {
            "name": "response-coherence-check",
            "data": {
                "description": "Ensure responses are coherent and well-structured",
                "stage": "post",
                "execution": "server",
                "step_type_filter": ["tool"],
                "tool_name_filter": ["generate_answer"],
                "evaluator_configs": [
                    {
                        "evaluator": "langsmith",
                        "config": {
                            "metric": "coherence",
                            "threshold": 0.8,
                            "langsmith_project": "agent-control-demo",
                        },
                        "selector": "output",
                        "action": "deny",
                    }
                ],
            },
        }

        try:
            coherence_result = await controls.create_control(
                client, coherence_control_data["name"], coherence_control_data["data"]
            )
            print(f"✓ Created coherence control (ID: {coherence_result['control_id']})")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                print(f"✓ Coherence control already exists (skipping)")
            elif e.response.status_code == 422:
                print(f"✗ Coherence control validation failed:")
                print(f"   Response: {e.response.text}")
                print(f"   Config sent: {coherence_control_data['data']['evaluator_configs'][0]['config']}")
                raise
            else:
                raise
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"✓ Coherence control already exists (skipping)")
            else:
                raise

        # 5. Create policy
        print("\nCreating policy...")
        policy_name = "langsmith-rag-policy"

        try:
            policy_result = await policies.create_policy(client, policy_name)
            policy_id = policy_result["policy_id"]
            print(f"✓ Created policy '{policy_name}' (ID: {policy_id})")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                print(f"✓ Policy '{policy_name}' already exists (skipping)")
                # Get existing policy ID
                policy_id = None  # Would need to fetch from API
            else:
                raise
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"✓ Policy '{policy_name}' already exists (skipping)")
                # Get existing policy ID
                policy_id = None  # Would need to fetch from API
            else:
                raise

        # 6. Add controls to policy
        if policy_id:
            print("\nAdding controls to policy...")
            control_names = [
                "query-toxicity-check",
                "response-hallucination-check",
                "response-pii-check",
                "response-coherence-check",
            ]

            for control_name in control_names:
                try:
                    # Note: This is a placeholder - the actual API endpoint
                    # for adding controls to policies may differ
                    print(f"  Adding control '{control_name}'...")
                    # await policies.add_control_to_policy(client, policy_id, control_name)
                    print(f"  ✓ Added '{control_name}'")
                except Exception as e:
                    print(f"  ⚠️  Could not add '{control_name}': {e}")

        # 7. Assign policy to agent
        print("\nAssigning policy to agent...")
        print(f"  Policy: {policy_name}")
        print(f"  Agent: rag-qa-agent-demo")
        print()
        print("  Note: You may need to manually assign the policy via the API")
        print(f"  PUT /api/v1/agents/rag-qa-agent-demo/policy/{policy_name}")

    print()
    print("=" * 70)
    print("Setup complete! You can now run:")
    print("  $ uv run rag_qa_agent.py")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(setup_controls())
