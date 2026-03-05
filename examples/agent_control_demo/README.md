# Agent Control Demo

Complete example demonstrating the Agent Control workflow: creating controls, running a controlled agent, and dynamically updating controls without code changes.

## Overview

This demo shows how to:
1. Create an agent and register it with the Agent Control server
2. Define controls (regex, list-based) and assign them to a policy
3. Run an agent that uses the `@control` decorator with server-side policies
4. Dynamically update controls on the server (enable/disable rules without redeploying code)

## Prerequisites

Before running this example:

1. **Start the Agent Control server** from the monorepo root:
   ```bash
    make server-run
   ```

2. **Verify server is running**:
   ```bash
   curl http://localhost:8000/health
   # Expected: {"status":"healthy","version":"..."}
   ```

3. **Install dependencies** (if not already done from monorepo root):
   ```bash
   make sync
   ```

## Quick Start

### Step 1: Create Controls on the Server

Run the setup script to create the agent, controls, and policy:

```bash
uv run python examples/agent_control_demo/setup_controls.py
```

This creates:
- A demo agent (`demo-chatbot`)
- Two controls:
  - **block-ssn-output**: Regex control to detect and block Social Security Numbers (SSN)
  - **block-banned-words**: List-based control to block profanity and sensitive keywords
- A policy with both controls assigned to the agent

### Step 2: Run the Demo Agent

Start the agent that uses server-side controls:

```bash
uv run python examples/agent_control_demo/demo_agent.py
```

The agent will:
- Initialize with `agent_control.init()` to connect to the server
- Load the assigned policy with all controls
- Apply the `@control()` decorator to protect functions
- Test various scenarios:
  - ✅ Normal message (allowed)
  - ❌ Message containing banned words (blocked)
  - ✅ Message with allowed content (passes)
  - ❌ Tool output containing SSN (blocked)

### Step 3: Update Controls Dynamically

Update controls on the server without changing code or restarting the agent:

```bash
# Disable the SSN control (allow SSNs)
uv run python examples/agent_control_demo/update_controls.py --allow-ssn

# Re-enable the SSN control (block SSNs again)
uv run python examples/agent_control_demo/update_controls.py --block-ssn
```

**Key Insight**: Controls are enforced server-side, so you can update rules in real-time without code deployments.

## Files

| File | Description |
|:-----|:------------|
| [setup_controls.py](setup_controls.py) | Creates agent, controls, policy, and assigns policy to agent |
| [demo_agent.py](demo_agent.py) | Demo agent using `@control` decorator with server-side policies |
| [update_controls.py](update_controls.py) | Updates controls dynamically (enable/disable SSN blocking) |

## How It Works

### 1. Server-Side Control Definition

Controls are defined on the server with:
- **Scope**: When to check (step types, stages: pre/post)
- **Selector**: What to check (input, output, specific fields)
- **Evaluator**: How to check (regex patterns, list matching, AI-based)
- **Action**: What to do (allow, deny, steer, warn, log)

Example from `setup_controls.py`:
```python
# Regex control to block SSN in output
control_data = ControlDefinition(
    description="Block SSN patterns in output",
    enabled=True,
    execution="server",
    scope=ControlScope(step_types=["tool"], stages=["post"]),
    selector=ControlSelector(path="output"),
    evaluator=EvaluatorConfig(
        name="regex",
        config={"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}
    ),
    action=ControlAction(decision="deny")
)
```

### 2. Agent Integration

The agent uses the `@control()` decorator which:
- Automatically fetches assigned policy from server
- Evaluates controls before/after function execution
- Blocks violations or allows safe operations

Example from `demo_agent.py`:
```python
import agent_control
from agent_control import control, ControlViolationError

# Initialize and connect to server
agent_control.init(
    agent_name="demo-chatbot",
)

# Apply server-side controls
@control()
async def chat(message: str) -> str:
    return f"Echo: {message}"

# Handle violations
try:
    response = await chat("user input")
except ControlViolationError as e:
    print(f"Blocked: {e.message}")
```

### 3. Dynamic Updates

Controls can be updated on the server without code changes:
- Enable/disable controls
- Update patterns and rules
- Change enforcement decisions (deny → warn)
- Add new controls to existing policies

## Configuration

All scripts use the same agent configuration:

```python
AGENT_NAME = "demo-chatbot"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
```

Set `AGENT_CONTROL_URL` environment variable to connect to a different server:
```bash
export AGENT_CONTROL_URL=http://your-server:8000
```

## Troubleshooting

### Server Connection Issues

**Error**: `Failed to connect to server`

**Fix**:
```bash
# Check if server is running
curl http://localhost:8000/health

# If not running, start it
make server-run
```

### Agent Not Found

**Error**: `Agent not found` when running `demo_agent.py`

**Fix**: Run `setup_controls.py` first to create the agent and controls:
```bash
uv run python examples/agent_control_demo/setup_controls.py
```

### Import Errors

**Error**: `ModuleNotFoundError: No module named 'agent_control'`

**Fix**: Install dependencies from monorepo root:
```bash
make sync
```

## Next Steps

- Explore [CONCEPTS.md](../../CONCEPTS.md) to understand controls, policies, scopes, and evaluators
- Check out [CrewAI example](../crewai/) for multi-agent orchestration with controls
- Read [SDK documentation](../../sdks/python/README.md) for full API reference
- Try [LangChain example](../langchain/) for LangChain integration

## Resources

- [Main Documentation](../../README.md)
- [SDK Documentation](../../sdks/python/README.md)
- [Server Documentation](../../server/README.md)
- [Models Documentation](../../models/README.md)
