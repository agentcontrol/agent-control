---
name: agent-control
description: Help users set up and use the Agent Control SDK to add runtime guardrails, monitoring, and protection to AI agents. Use when working with agent-control-sdk, adding controls, policies, or the @control() decorator.
---

# Agent Control SDK

Agent Control provides runtime guardrails for AI agents. Controls are managed
server-side and enforced by the SDK without code changes.

## Quick Start

```python
import agent_control
from agent_control import control, ControlViolationError

# 1. Initialize (call once at startup)
agent_control.init(
    agent_name="My Agent",
    agent_id="550e8400-e29b-41d4-a716-446655440000",
    server_url="http://localhost:8000",
)

# 2. Protect functions with @control()
@control()
async def handle_message(message: str) -> str:
    return await llm.generate(message)

# 3. Handle violations
try:
    result = await handle_message(user_input)
except ControlViolationError as e:
    print(f"Blocked by '{e.control_name}': {e.message}")
```

## Environment Variables

- `AGENT_CONTROL_URL` - Server URL (default: http://localhost:8000)
- `AGENT_CONTROL_API_KEY` - API key for authentication
- `AGENT_CONTROL_OBSERVABILITY_ENABLED` - Enable event batching

## init() Parameters

```python
agent_control.init(
    agent_name="...",              # Required: human-readable name
    agent_id="UUID-string",        # Required: unique UUID
    agent_description="...",       # Optional
    agent_version="1.0.0",        # Optional
    server_url="http://...",       # Optional (env: AGENT_CONTROL_URL)
    api_key="...",                 # Optional (env: AGENT_CONTROL_API_KEY)
    steps=[                        # Optional: register agent's tools/steps
        {"type": "tool", "name": "search", "input_schema": {...}}
    ],
    observability_enabled=True,    # Optional
)
```

## @control() Decorator

```python
from agent_control import control

@control()                          # Uses agent's assigned policy
async def my_func(text: str) -> str: ...

@control(policy="strict-policy")    # Uses a specific policy
async def sensitive_func(data: str) -> str: ...
```

The decorator automatically runs pre/post checks and raises `ControlViolationError` on deny.

## Control Anatomy

Each control has 4 parts:

| Component | Purpose | Example |
|-----------|---------|---------|
| **Scope** | When to check | `{"step_types": ["llm"], "stages": ["post"]}` |
| **Selector** | What to extract | `{"path": "output"}` |
| **Evaluator** | How to evaluate | `{"name": "regex", "config": {"pattern": "\\d{3}-\\d{2}-\\d{4}"}}` |
| **Action** | What to do | `{"decision": "deny"}` |

## Creating Controls via API

```python
await agent_control.create_control(
    name="block-ssn",
    data={
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "selector": {"path": "output"},
        "evaluator": {"name": "regex", "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}},
        "action": {"decision": "deny"},
    },
)
```

## Common Operations

```python
# List agents
agents = await agent_control.list_agents()

# List controls
controls = await agent_control.list_controls(enabled=True, step_type="llm")

# Refresh controls (after server-side changes)
agent_control.refresh_controls()

# Add control to policy
await agent_control.add_control_to_policy(policy_id=1, control_id=5)
```

## Built-in Evaluators

- **regex** - Pattern matching (SSN, credit cards, emails)
- **list** - Block/allow specific strings (SQL keywords, domains)
- **luna-2** - AI-powered toxicity detection (requires galileo extra)

## Important Notes

- Always call `agent_control.init()` before using `@control()`
- The `agent_id` must be a valid UUID string
- Controls are defined server-side, not in code
- `@control()` works with both async and sync functions
- Install: `pip install agent-control-sdk` / Import: `import agent_control`
