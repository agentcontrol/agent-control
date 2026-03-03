#!/usr/bin/env python3
"""
Demo agent that uses server-side controls.

This agent demonstrates how the @control decorator works
with controls defined on the server.

Prerequisites:
    1. Agent Control server running: cd server && make run
    2. Controls created: python setup_controls.py

Usage:
    python demo_agent.py
"""

import asyncio
import logging
import os
import sys

# Configure logging to see SDK debug output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Enable SDK logs at DEBUG level to see all control evaluations
logging.getLogger('agent_control').setLevel(logging.DEBUG)

# Suppress noisy HTTP library logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

# Demo script logger
logger = logging.getLogger(__name__)

# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

import agent_control
from agent_control import control, ControlViolationError


# Configuration
AGENT_NAME = "demo-chatbot"
AGENT_ID = "672e50df-af4c-429f-965a-3d7f8262302f"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


# =============================================================================
# SIMULATED LLM / BACKEND
# =============================================================================

def simulate_llm_response(query: str) -> str:
    """Simulate an LLM generating a response."""
    # This simulates various LLM responses, some containing sensitive data
    responses = {
        "user info": "The user's SSN is 456-22-6789 and their email is galileo@galileo.ai",
        "safe": "I'd be happy to help you with that question!",
        "help": "Here are some things I can assist you with...",
    }
    
    for key, response in responses.items():
        if key in query.lower():
            return response
    
    return f"I processed your query: {query}"


def simulate_database_query(sql: str) -> str:
    """Simulate a database query."""
    return f"Query executed: {sql}"


# =============================================================================
# AGENT FUNCTIONS WITH CONTROLS
# =============================================================================

@control()
async def chat(message: str) -> str:
    """
    Chat function protected by agent-associated controls.

    The 'block-ssn-output' control checks OUTPUT for SSN patterns.
    This prevents PII leakage in responses.
    """
    print(f"  [Agent] Processing message: {message}")
    response = simulate_llm_response(message)
    print(f"  [Agent] Generated response: {response[:50]}...")
    return response


@control()
async def execute_query(query: str) -> str:
    """
    Database query function protected by agent-associated controls.

    The 'block-dangerous-sql' control checks INPUT for dangerous
    SQL keywords and blocks before execution.
    """
    print(f"  [Agent] Executing query: {query}")
    result = simulate_database_query(query)
    print(f"  [Agent] Query result: {result}")
    return result


@control()  # Apply agent-associated controls
async def process_request(input: str) -> str:
    """
    General processing function with agent-associated controls applied.

    Controls directly associated to the agent are evaluated.
    """
    print(f"  [Agent] Processing request: {input}")
    response = simulate_llm_response(input)
    print(f"  [Agent] Response: {response[:50]}...")
    return response


# =============================================================================
# TEST SCENARIOS
# =============================================================================

async def test_scenario(name: str, func, input_text: str):
    """Run a test scenario and show results."""
    logger.debug(f"Running test: {name}")
    print(f"\n{'─' * 60}")
    print(f"📝 TEST: {name}")
    print(f"{'─' * 60}")
    print(f"Input: \"{input_text}\"")
    print()

    try:
        result = await func(input_text)
        logger.debug(f"Test '{name}' passed")
        print(f"\n✅ SUCCESS - Response returned:")
        print(f"   \"{result[:100]}{'...' if len(result) > 100 else ''}\"")
    except ControlViolationError as e:
        logger.debug(f"Test '{name}' blocked by control: {e.control_name}")
        print(f"\n🚫 BLOCKED by control: {e.control_name}")
        print(f"   Reason: {e.message}")
        if e.metadata:
            print(f"   Metadata: {e.metadata}")
    except Exception as e:
        logger.error(f"Test '{name}' failed with error: {e}")
        print(f"\n❌ ERROR: {e}")


async def run_demo():
    """Run the demo scenarios."""
    logger.info("Starting agent control demo")
    print("\n" + "=" * 60)
    print("AGENT CONTROL DEMO: Running Agent")
    print("=" * 60)

    # Initialize the agent
    print(f"\n🤖 Initializing agent: {AGENT_NAME}")
    print(f"   Server: {SERVER_URL}")

    try:
        logger.info(f"Initializing agent: {AGENT_NAME}")
        agent_control.init(
            agent_name=AGENT_ID,
            agent_description=AGENT_NAME,
            server_url=SERVER_URL,
        )
        logger.info("Agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}")
        print(f"\n❌ Failed to initialize agent: {e}")
        print("\nMake sure:")
        print("  1. Server is running: cd server && make run")
        print("  2. Controls are created: python setup_controls.py")
        return

    # ==========================================================================
    # Test 1: Safe chat message
    # ==========================================================================
    await test_scenario(
        "Safe Chat Message",
        chat,
        "Hello, how can you help me today?"
    )

    # ==========================================================================
    # Test 2: Chat that would leak SSN (should be blocked by OUTPUT control)
    # ==========================================================================
    await test_scenario(
        "Chat Request That Would Leak SSN",
        chat,
        "Tell me the user info"  # Response contains SSN, should be blocked
    )

    # ==========================================================================
    # Test 3: Safe SQL query
    # ==========================================================================
    await test_scenario(
        "Safe SQL Query",
        execute_query,
        "SELECT * FROM users WHERE id = 123"
    )

    # ==========================================================================
    # Test 4: Dangerous SQL query (should be blocked by INPUT control)
    # ==========================================================================
    await test_scenario(
        "Dangerous SQL - DROP TABLE",
        execute_query,
        "DROP TABLE users"  # Should be blocked before execution
    )

    # ==========================================================================
    # Test 5: Another dangerous SQL query
    # ==========================================================================
    await test_scenario(
        "Dangerous SQL - DELETE",
        execute_query,
        "DELETE FROM users WHERE 1=1"  # Should be blocked
    )

    # ==========================================================================
    # Test 6: Process request with all controls
    # ==========================================================================
    await test_scenario(
        "Process Safe Request (All Controls)",
        process_request,
        "What's the weather today?"
    )

    # ==========================================================================
    # Test 7: Process request that triggers output control
    # ==========================================================================
    await test_scenario(
        "Process Request with PII in Response (All Controls)",
        process_request,
        "Get user info"  # Will generate response with SSN
    )

    # Summary
    logger.info("All demo scenarios completed")
    print("\n" + "=" * 60)
    print("DEMO COMPLETE!")
    print("=" * 60)
    print("""
Summary:
  ✅ Safe requests passed through
  🚫 Dangerous SQL blocked by INPUT control (pre-execution)
  🚫 PII in response blocked by OUTPUT control (post-execution)

The controls are evaluated SERVER-SIDE:
  - Change thresholds/patterns on server without code changes
  - All evaluations logged for audit
  - Centralized control management
""")


if __name__ == "__main__":
    asyncio.run(run_demo())
