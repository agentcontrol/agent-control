"""
Example using the agent_control.init() and @control decorator.

This demonstrates the SDK approach for server-side control evaluation:
1. Initialize with agent_control.init() - registers with server
2. Use @control() decorator - evaluates policies server-side
"""

import asyncio

import agent_control
from agent_control import ControlViolationError, control

# ============================================================================
# STEP 1: Initialize at the base of your agent
# ============================================================================
agent_control.init(
    agent_name="Example Customer Service Bot",
    agent_id="csbot-example-v1",
    agent_description="Handles customer inquiries with safety checks",
    agent_version="1.0.0",
    # Optional: Add any custom metadata
    team="customer-success",
    environment="development"
)


# ============================================================================
# STEP 2: Use @control decorator on your functions
# ============================================================================
@control()  # Applies the agent's assigned policy from server
async def check_before_llm(content: str, ctx: dict) -> str:
    """
    This function is protected by server-side controls.

    The @control() decorator:
    - Calls server with check_stage="pre" before execution
    - Calls server with check_stage="post" after execution
    - Raises ControlViolationError on "deny" actions
    """
    return f"Processed: {content}"


@control()  # Same - uses agent's policy
async def generate_response(query: str, ctx: dict) -> str:
    """Response is validated against server controls."""
    # Simulate LLM response
    response = f"Response to {query}: Contact support@example.com or call 555-123-4567"
    return response


# ============================================================================
# STEP 3: Use your protected functions
# ============================================================================
async def main():
    """Demonstrate the agent_control SDK approach."""

    print("=" * 80)
    print("AGENT CONTROL - SERVER-SIDE EVALUATION")
    print("=" * 80)
    print()

    # Get agent info (use current_agent() which is sync)
    agent = agent_control.current_agent()
    if agent:
        print(f"Agent Name: {agent.agent_name}")
        print(f"Agent ID: {agent.agent_id}")
        print(f"Description: {agent.agent_description}")
        print(f"Version: {agent.agent_version}")
    else:
        print("⚠️  No agent initialized")
    print()

    # Test 1: Safe input
    print("Test 1: Safe input")
    print("-" * 80)
    try:
        result = await check_before_llm(
            "Hello, I need help with my order",
            {"user_id": "user123", "session": "abc"}
        )
        print(f"✓ Success: {result}")
    except ControlViolationError as e:
        print(f"✗ Blocked by [{e.control_name}]: {e.message}")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    print()

    # Test 2: Input that might trigger a control
    print("Test 2: Another input")
    print("-" * 80)
    try:
        result = await check_before_llm(
            "Hi, my name is Nachiket and I need help",
            {"user_id": "user123"}
        )
        print(f"✓ Success: {result}")
    except ControlViolationError as e:
        print(f"✗ Blocked by [{e.control_name}]: {e.message}")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    print()

    # Test 3: Output check
    print("Test 3: Generate response")
    print("-" * 80)
    try:
        result = await generate_response(
            "How do I contact support?",
            {"user_id": "user123"}
        )
        print(f"✓ Success: {result}")
    except ControlViolationError as e:
        print(f"✗ Blocked by [{e.control_name}]: {e.message}")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("""
How @control() works:
1. @control() decorator wraps your function
2. Before execution: calls server with check_stage="pre"
3. Your function executes
4. After execution: calls server with check_stage="post"
5. If any control matches with "deny" action → ControlViolationError

Server Setup (required before running):
1. Start server: cd server && make run
2. Create controls: uv run python examples/agent_control_demo/setup_controls.py
3. Run this demo!

Usage:
  import agent_control
  agent_control.init(agent_name='...', agent_id='...')

  from agent_control import control, ControlViolationError

  @control()
  async def my_function(input: str) -> str:
      return process(input)
""")


if __name__ == "__main__":
    asyncio.run(main())
