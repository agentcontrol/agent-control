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

### 🧩 TypeScript SDK (`typescript_sdk/`)

Consumer-style TypeScript example that installs `agent-control` from npm and calls the Agent Control API:

```bash
cd examples/typescript_sdk
npm install
AGENT_CONTROL_URL=http://localhost:8000 npm run start
```

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
- `demo_agent.py` - Agent that uses `@control` decorator with server-side controls
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

### 🔄 Steer Action Demo (`steer_action_demo/`)

**NEW!** Autonomous agent with self-correction using steer actions:

```bash
cd examples/steer_action_demo

# 1. Setup steer controls
uv run setup_controls.py

# 2. Run autonomous agent (uses LangGraph)
uv run autonomous_agent_demo.py

# OR: Run interactive CLI demo
uv run interactive_demo.py
```

**What it demonstrates:**
- ✅ **Steer actions** - Corrective steering context instead of hard blocks
- ✅ **Autonomous retry** - Agent automatically revises based on feedback
- ✅ **LangGraph workflow** - State-managed revision loop
- ✅ **Multiple controls** - Language, PII, length, completeness checks

**Key Features:**
- Agent generates content → Gets steer steering context → Autonomously revises → Succeeds or fails after max retries
- Shows difference between `ControlSteerError` (can retry) vs `ControlViolationError` (hard block)
- Real-world use cases: inappropriate language, PII exposure, length limits, missing information

See [steer_action_demo/README.md](steer_action_demo/README.md) for details.

## Common Patterns

### Pattern 1: Using @control Decorator (Server-Side)

```python
import agent_control
from agent_control import control, ControlViolationError

# Initialize agent (connects to server, loads control associations)
agent_control.init(
    agent_name="my-bot",
    agent_description="My Bot",
)

# Apply controls associated with the agent
@control()
async def chat(message: str) -> str:
    return await assistant.respond(message)

# Handle violations
try:
    response = await chat("user input")
except ControlViolationError as e:
    print(f"Blocked: {e.message}")
```

### Pattern 2: Using Steer Actions for Autonomous Retry

```python
import agent_control
from agent_control import control, ControlSteerError, ControlViolationError

agent_control.init(agent_name="my-bot", agent_description="My Bot")

@control()
async def generate_content(prompt: str) -> str:
    return await llm.generate(prompt)

# Autonomous retry with steering context
async def generate_with_retry(prompt: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return await generate_content(prompt)
        except ControlSteerError as e:
            # Steer: can retry with corrections
            print(f"Steering context: {e.steering_context}")
            if attempt < max_retries - 1:
                # Revise prompt based on steering context
                prompt = f"{prompt}\n\nRevise to: {e.steering_context}"
            else:
                raise
        except ControlViolationError as e:
            # Deny: cannot proceed
            print(f"Blocked: {e.message}")
            raise
```

### Pattern 3: Direct SDK Usage

```python
from agent_control import AgentControlClient

async with AgentControlClient() as client:
    # Check server health
    health = await client.health_check()

    # Make API calls via http_client
    response = await client.http_client.get("/api/v1/controls")
```

### Pattern 4: Programmatic Control Setup

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
- [TypeScript SDK Documentation](../sdks/typescript/README.md)
- [Server Documentation](../server/README.md)
- [Models Documentation](../models/README.md)
