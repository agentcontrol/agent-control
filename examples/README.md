# Agent Control Examples

This directory contains examples demonstrating how to use Agent Control in various scenarios.

## Quick Start

### Prerequisites

1. Start the Agent Control server:
   ```bash
   cd server && make run
   ```

2. (Optional) Set environment variables:
   ```bash
   export AGENT_CONTROL_URL=http://localhost:8000
   export OPENAI_API_KEY=your_key_here  # For LangGraph examples
   ```

## Example Categories

### 🚀 Agent Control Demo (`agent_control_demo/`)

Complete examples showing the agent control workflow:

```bash
# 1. Create controls on the server
uv run python examples/agent_control_demo/setup_controls.py

# 2. Run the demo agent with controls
uv run python examples/agent_control_demo/demo_agent.py

# 3. Update controls dynamically
uv run python examples/agent_control_demo/update_controls.py --allow-ssn
uv run python examples/agent_control_demo/update_controls.py --block-ssn
```

**Files:**
- `setup_controls.py` - Create and configure controls via SDK
- `demo_agent.py` - Agent that uses `@control` decorator with server-side policies
- `update_controls.py` - Dynamically update controls without code changes
- `agent_luna_demo.py` - Luna-2 evaluator integration for AI safety checks

### 💬 Simple Chatbot (`demo_chatbot.py`)

Interactive chatbot demonstrating the `@control` decorator:

```bash
uv run python examples/demo_chatbot.py
```

### 🔧 Control Setup (`demo_setup_controls.py`)

Programmatic control setup using SDK models:

```bash
uv run python examples/demo_setup_controls.py
```

### 🤖 LangGraph Integration (`langchain/`)

LangGraph examples are available in `examples/langchain`:

```bash
cd examples/langchain
uv run langgraph_auto_schema_agent.py
```

This specific example demonstrates auto-derived step schemas from `@control()`
decorators, so no explicit `steps=...` list is required in `agent_control.init(...)`.

### 🛡️ Luna-2 Demo (`luna2_demo.py`)

Direct integration with Galileo Protect API:

```bash
export GALILEO_API_KEY=your_key_here
uv run python examples/luna2_demo.py
```

## Common Patterns

### Pattern 1: Using @control Decorator (Server-Side)

```python
import agent_control
from agent_control import control, ControlViolationError

# Initialize agent (connects to server, loads policy)
agent_control.init(
    agent_name="my-bot",
    agent_id="550e8400-e29b-41d4-a716-446655440000",
)

# Apply the agent's assigned policy
@control()
async def chat(message: str) -> str:
    return await assistant.respond(message)

# Handle violations
try:
    response = await chat("user input")
except ControlViolationError as e:
    print(f"Blocked: {e.message}")
```

### Pattern 2: Direct SDK Usage

```python
from agent_control import AgentControlClient

async with AgentControlClient() as client:
    # Check server health
    health = await client.health_check()
    
    # Make API calls via http_client
    response = await client.http_client.get("/api/v1/controls")
```

### Pattern 3: Programmatic Control Setup

```python
from agent_control import (
    AgentControlClient,
    ControlDefinition,
    ControlSelector,
    ControlScope,
    ControlAction,
    EvaluatorSpec,
    controls,
)

async with AgentControlClient() as client:
    # Create control
    ctrl = await controls.create_control(client, "block-pii")
    
    # Configure control
    control_data = ControlDefinition(
        description="Block PII in output",
        enabled=True,
        execution="server",
        scope=ControlScope(step_types=["llm"], stages=["post"]),
        selector=ControlSelector(path="output"),
        evaluator=EvaluatorSpec(
            name="regex",
            config={"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}
        ),
        action=ControlAction(decision="deny")
    )
    await controls.set_control_data(client, ctrl["control_id"], control_data)
```

## Testing Examples

```bash
# Run from repo root
cd examples/langgraph/my_agent
pytest test_agent.py -v
```

## Troubleshooting

### Server Connection Issues

```bash
# Check if server is running
curl http://localhost:8000/health
# Expected: {"status":"healthy","version":"0.1.0"}
```

### Import Errors

```bash
# Install the SDK from workspace root
make sync

# Or install directly
pip install -e sdks/python
```

## Resources

- [Main Documentation](../README.md)
- [SDK Documentation](../sdks/python/README.md)
- [Server Documentation](../server/README.md)
- [Models Documentation](../models/README.md)
