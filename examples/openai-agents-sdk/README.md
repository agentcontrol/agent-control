# openai-agents SDK with Agent Control

This example demonstrates integrating Agent Control with the openai-agents SDK to add runtime guardrails to tool calls.

## What You'll Learn

- How to add agent control to the **openai-agents SDK**
- **Three-layer defense-in-depth** protection for sensitive data (SSN)
- Protecting tool calls with the `@control()` decorator
- Using context with agents for personalized behavior

## Defense-in-Depth Strategy

This example demonstrates **three layers of protection** to prevent SSN exposure:

1. **Layer 1 (Pre-LLM)**: Block SSN patterns in user input
   - Prevents LLM from ever seeing SSN
   - Control: `llm_call` pre-stage with regex

2. **Layer 2 (Pre-Tool)**: Block tool calls requesting SSN field
   - Prevents tool from being called with sensitive field
   - Control: `tool_call` pre-stage with list evaluator

3. **Layer 3 (Post-Tool)**: Block SSN patterns in tool output
   - Catches accidental SSN leaks (e.g., bugs in tool code)
   - Control: `tool_call` post-stage with regex

**Why three layers?** Even if your tool has a bug (like our 'all' field that returns everything), the post-tool control catches it!

## Prerequisites

### 1. Start the Agent Control Server

```bash
# From the repo root
cd server
make run
```

**Verify server is running:**
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy",...}
```

### 2. Set OpenAI API Key

```bash
export OPENAI_API_KEY="your-key-here"
```

### 3. Setup Controls (One-Time)

```bash
cd examples/openai-agents-sdk
uv run setup_controls.py
```

This creates:
- Agent registration
- **Three SSN protection controls:**
  - Control 1: Block SSN in user input (pre-LLM)
  - Control 2: Block SSN field in tool args (pre-tool)
  - Control 3: Block SSN in tool output (post-tool)
- Policy with all three controls
- Assigns policy to the agent

## Running the Example

```bash
cd examples/openai-agents-sdk
uv run user_data_agent_protection.py
```

### Expected Behavior

**Scenario 1: Safe Request (No Protection Triggered)**
```
User: What is my name and email?
✅ Tool execution allowed
Agent: Your name is Alice Johnson and your email is alice@example.com.
```

**Scenario 2: Layer 1 Protection (Pre-LLM)**
```
User: My SSN is 123-45-6789. Can you verify my account?
⛔ Blocked BEFORE reaching LLM
Error: Control evaluation failed (SSN pattern detected in input)
```

**Scenario 3: Layer 2 Protection (Pre-Tool)**
```
User: What is my SSN?
Agent tries to call: get_user_data(fields=["ssn"])  # user_id from context
⛔ Tool call blocked: SSN field access is not allowed
Agent: I apologize, but I cannot access SSN information due to security policies.
```

**Scenario 4: Layer 3 Protection (Post-Tool)**
```
User: Show me all my information using the 'all' field
Agent calls: get_user_data(fields=["all"])  # user_id from context
Tool executes and returns: {"name": "Alice", ..., "ssn": "123-45-6789"}
⛔ Tool output blocked: SSN pattern detected in output
Agent receives error instead of SSN
```

## Protection Pattern

This example uses a **two-level protection strategy**:

1. **LLM-level protection** (`@control()` on runner function):
   - Wraps the entire `Runner.run()` call
   - Enables Pre-LLM controls (e.g., block SSN in user input before it reaches the LLM)
   - Enables Post-LLM controls (e.g., block sensitive content in final agent output)
   - Simpler than trying to hook into the SDK's internal LLM calls

2. **Tool-level protection** (`@control()` on individual tools):
   - Wraps each tool function separately
   - Enables Pre-Tool controls (e.g., block calls requesting sensitive fields)
   - Enables Post-Tool controls (e.g., block tool outputs containing sensitive patterns)
   - Catches bugs where tools accidentally return sensitive data

**Why this pattern?** The openai-agents SDK doesn't expose hooks for internal LLM calls, so we wrap the entire agent runner instead. This gives us control over what goes IN and what comes OUT, while individual tool wrapping handles tool-specific controls.

## How It Works

### 1. openai-agents SDK Structure

```python
from agents import Agent, Runner, function_tool, RunContextWrapper

# Define context type
@dataclass
class UserContext:
    user_id: str
    user_name: str

# Create agent with context type
agent = Agent[UserContext](
    name="User Data Assistant",
    instructions=get_agent_instructions,  # Can be dynamic function
    model="gpt-4.1-mini",
    tools=[get_user_data],
)

# Run agent with context
result = await Runner.run(agent, user_message, context=user_context)
```

### 2. Protecting the Agent Runner (LLM Protection)

```python
@control()
async def run_protected_agent(agent_input: str, user_context: UserContext):
    """
    Protected agent runner with LLM-level guardrails.
    Enables Pre-LLM and Post-LLM controls (e.g., block SSN in user input).
    """
    result = await Runner.run(user_agent, agent_input, context=user_context)
    return result

# Use it
result = await run_protected_agent(user_message, user_context)
```

### 3. Protecting Tools (Tool Protection)

```python
# Inner function with @control decorator
async def _get_user_data_with_validation(user_id: str, fields: list[str]) -> str:
    return _get_user_data(user_id, fields)

# Set tool name for @control detection
_get_user_data_with_validation.name = "get_user_data"
_get_user_data_with_validation.tool_name = "get_user_data"

# Apply @control decorator
protected_get_user_data = control()(_get_user_data_with_validation)

# Wrap with function_tool for openai-agents SDK
@function_tool
async def get_user_data(ctx: RunContextWrapper[UserContext], fields: list[str]) -> str:
    """Retrieve user data with tool-level protection."""
    user_id = ctx.context.user_id
    
    try:
        result = await protected_get_user_data(user_id, fields)
        return result
    except ControlViolationError as e:
        return json.dumps({"error": f"Blocked: {e.message}"})
```

### 4. Server-Side Controls (Three Layers)

**Control 1: Pre-LLM Input Validation**
```python
{
    "enabled": True,
    "execution": "server",
    "scope": {
        "step_types": ["llm_inference"],
        "stages": ["pre"]
    },
    "selector": {"path": "input"},
    "evaluator": {
        "plugin": "regex",
        "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}  # SSN pattern
    },
    "action": {"decision": "deny"}
}
```

**Control 2: Pre-Tool Argument Validation**
```python
{
    "enabled": True,
    "execution": "server",
    "scope": {
        "step_types": ["tool"],
        "step_names": ["get_user_data"],
        "stages": ["pre"]
    },
    "selector": {
        "path": "input.fields"
    },
    "evaluator": {
        "plugin": "list",
        "config": {
            "values": ["ssn"],
            "case_sensitive": False
        }
    },
    "action": {"decision": "deny"}
}
```

**Control 3: Post-Tool Output Validation**
```python
{
    "enabled": True,
    "execution": "server",
    "scope": {
        "step_types": ["tool"],
        "step_names": ["get_user_data"],
        "stages": ["post"]
    },
    "selector": {
        "path": "output"
    },
    "evaluator": {
        "plugin": "regex",
        "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}
    },
    "action": {"decision": "deny"}
}
```

### 5. Dynamic Instructions with Context

```python
def get_agent_instructions(ctx: RunContextWrapper[UserContext], agent: Agent) -> str:
    return f"""You are helping {ctx.context.user_name} (ID: {ctx.context.user_id})
    
When the user asks about "my" data, use user_id = '{ctx.context.user_id}'."""

agent = Agent[UserContext](
    instructions=get_agent_instructions,
    ...
)
```

## Architecture: Three-Layer Protection

```
User: "My SSN is 123-45-6789. What's my balance?"
    ↓
run_protected_agent() - wrapped with @control()
    ↓
🛡️  LAYER 1: Pre-LLM Check
    ├─ Control checks input for SSN pattern
    ├─ Regex finds "123-45-6789"
    └─ ⛔ BLOCKED - LLM never sees this input

---

User: "What is my SSN?"
    ↓
run_protected_agent() - wrapped with @control()
    ↓
openai-agents SDK (Runner.run)
    ↓
Agent decides: get_user_data(fields=["ssn"])
    ↓
get_user_data() calls protected_get_user_data()
    ↓
🛡️  LAYER 2: Pre-Tool Check
    ├─ @control() decorator intercepts
    ├─ Server checks arguments.fields for "ssn"
    ├─ List evaluator finds match
    └─ ⛔ BLOCKED - Tool never executes

---

User: "Show me all my data"
    ↓
run_protected_agent() - wrapped with @control()
    ↓
openai-agents SDK (Runner.run)
    ↓
Agent decides: get_user_data(fields=["all"])
    ↓
Pre-Tool Check: ✅ "all" is allowed
    ↓
Tool executes: returns {"name": "Alice", "ssn": "123-45-6789", ...}
    ↓
🛡️  LAYER 3: Post-Tool Check
    ├─ Control scans output for SSN pattern
    ├─ Regex finds "123-45-6789" in output
    └─ ⛔ BLOCKED - Agent receives error instead of SSN
```

## Files

- `user_data_agent_protection.py` - Main agent example with protected tools
- `setup_controls.py` - One-time setup script using Agent Control SDK
- `pyproject.toml` - Dependencies (openai-agents, Agent Control)
- `README.md` - This file


## Troubleshooting

### "Agent not found" or "Policy not assigned"

**Fix:**
```bash
uv run setup_controls.py
```

### "Policy 'openai-agents-policy' already exists"

**Fix:** Delete the existing policy or use a different name:
```bash
# Find policy ID
curl http://localhost:8000/api/v1/policies | jq

# Delete policy
curl -X DELETE http://localhost:8000/api/v1/policies/<policy_id>
```

### Tool calls not being blocked

**Causes:**
1. Server not running
2. Control not enabled in policy
3. Wrong agent ID or tool name

**Fix:**
1. Restart server: `cd server && make run`
2. Re-run setup: `uv run setup_controls.py`
3. Check agent ID matches in both setup and agent code

## Relevant Links

- Read the [main documentation](../../README.md)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
