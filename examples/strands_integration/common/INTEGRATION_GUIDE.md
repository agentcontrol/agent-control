# AgentControl + Strands Integration Guide

## Overview

This guide explains how AgentControl integrates with AWS Strands agents using a hook-based architecture for automatic safety enforcement.

## Core Concepts

### What is AgentControl?

**AgentControl** is a governance framework for AI agents that enforces safety policies in real-time. It evaluates agent inputs, outputs, and tool calls against configurable safety rules called **controls**.

Think of it as a security checkpoint that validates every action your agent takes before it reaches users or external systems.

### What is a Hook?

A **hook** is an event interceptor in the Strands framework. Hooks register callback functions that execute automatically when specific agent lifecycle events occur, such as:

- **BeforeInvocationEvent** - User sends a message
- **BeforeModelCallEvent** - About to call the LLM
- **AfterModelCallEvent** - LLM returns a response
- **BeforeToolCallEvent** - About to execute a tool
- **AfterToolCallEvent** - Tool returns results

Hooks enable you to inject custom logic (like safety checks) at precise moments in the agent's execution flow without modifying the agent code itself.

### What is a Control?

A **control** is a safety rule that defines:
1. **What to check** - Which data to evaluate (input, output, tool parameters)
2. **When to check** - Pre-stage (before action) or post-stage (after action)
3. **How to check** - Evaluation logic (regex patterns, LLM-based checks, custom logic)
4. **What to do** - Action when rule triggers (deny, allow, modify)

Example control:
```python
{
    "name": "block-pii-input",
    "scope": {
        "step_types": ["llm"],      # Check all LLM calls
        "stages": ["pre"]            # Check before LLM sees input
    },
    "evaluator": {
        "name": "regex",
        "config": {
            "pattern": r"\b\d{3}-\d{2}-\d{4}\b"  # SSN pattern
        }
    },
    "action": {
        "decision": "deny"           # Block if pattern found
    }
}
```

This control blocks any SSN patterns in user input before they reach the LLM.

## How Hooks and Controls Work Together

The `AgentControlHook` bridges Strands events and AgentControl safety checks:

```
┌─────────────────────────────────────────────────────────────┐
│                      Strands Agent                          │
│                                                             │
│  1. User sends message: "My SSN is 123-45-6789"            │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │   BeforeInvocationEvent      │ ← Strands fires event
         └──────────────┬───────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │    AgentControlHook          │
         │  (Hook callback executes)    │
         ├──────────────────────────────┤
         │ 2. Extracts message text     │
         │ 3. Creates Step object       │
         │    Step(type="llm",          │
         │         input="My SSN...")   │
         └──────────────┬───────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │   AgentControl Server        │
         ├──────────────────────────────┤
         │ 4. Finds matching controls   │
         │    → "block-pii-input"       │
         │       (step_types=["llm"])   │
         │ 5. Runs regex evaluator      │
         │    → Pattern matches! 🚨     │
         │ 6. Returns: is_safe=False    │
         └──────────────┬───────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │    AgentControlHook          │
         ├──────────────────────────────┤
         │ 7. Sees is_safe=False        │
         │ 8. Raises ControlViolation   │
         │ 9. Triggers retry with       │
         │    guidance: "Remove PII"    │
         └──────────────┬───────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │      Strands Agent           │
         ├──────────────────────────────┤
         │ 10. Retries without SSN      │
         │ 11. Success! ✅              │
         └──────────────────────────────┘
```

**Key insight:** The hook acts as a translator, converting Strands events into AgentControl Steps, then enforcing the control decisions.

## Two Types of Controls

### 1. LLM Controls (General Safety)

LLM controls apply to **all** model calls regardless of tool usage:

```python
{
    "scope": {
        "step_types": ["llm"],   # Matches all LLM interactions
        "stages": ["pre"]         # or ["post"]
    }
}
```

**Use cases:**
- Block PII in user input (pre-stage)
- Block PII in agent output (post-stage)
- Prevent toxic language
- Detect hallucinations
- Enforce response quality

**Hook events:** BeforeInvocationEvent, BeforeModelCallEvent, AfterModelCallEvent

### 2. Tool-Specific Controls (Validation)

Tool controls target **specific tools** by name:

```python
{
    "scope": {
        "step_types": ["tool"],
        "step_names": ["lookup_order"],  # Only this tool!
        "stages": ["pre"]
    }
}
```

**How tool targeting works:**
1. Agent decides to call `lookup_order` tool
2. Strands fires `BeforeToolCallEvent` with tool name and parameters
3. Hook extracts: `tool_name="lookup_order"`, `input={"order_id": "ORD-12345"}`
4. Hook creates: `Step(type="tool", name="lookup_order", input=...)`
5. Controls with `step_names=["lookup_order"]` match automatically!
6. Control validates the order ID format
7. If invalid, hook blocks the tool call

**Use cases:**
- Validate tool input formats (order IDs, dates, emails)
- Prevent SQL injection in search queries
- Rate limit expensive operations
- Filter sensitive data from tool outputs
- Enforce business rules (e.g., dollar amount limits)

**Hook events:** BeforeToolCallEvent, AfterToolCallEvent

**Key advantage:** No need to add `@control()` decorators to every tool function! The hook handles everything automatically by extracting tool names from events.

## Integration Architecture

### Single Hook, Multiple Controls

One `AgentControlHook` instance handles all safety checks:

```python
from common import AgentControlHook
from strands import Agent
from strands.hooks import BeforeInvocationEvent, AfterModelCallEvent, BeforeToolCallEvent

# Initialize AgentControl
import agent_control
agent_control.init(
    agent_name="support-agent",
    agent_id="550e8400-e29b-41d4-a716-446655440000"
)

# Create hook (handles all events)
hook = AgentControlHook(
    agent_uuid=UUID("550e8400-e29b-41d4-a716-446655440000"),
    agent_name="support-agent",
    event_control_list=[
        BeforeInvocationEvent,   # Check user input
        AfterModelCallEvent,     # Check agent output
        BeforeToolCallEvent,     # Check tool calls
    ]
)

# Attach to agent
agent = Agent(
    model=model,
    instructions="You are a helpful support agent",
    tools=[lookup_order, search_kb],
    hooks=[hook]  # Single hook for all safety!
)
```

The server-side controls configuration determines what gets checked:
- Controls with `step_types=["llm"]` → Applied to all LLM events
- Controls with `step_types=["tool"], step_names=["lookup_order"]` → Applied only to lookup_order tool

### Data Flow

1. **Event Capture**
   - Strands fires event (e.g., BeforeToolCallEvent)
   - Hook callback executes automatically

2. **Step Creation**
   - Hook extracts relevant data from event
   - Creates AgentControl `Step` object:
     - `type`: "llm" or "tool"
     - `name`: Event-specific (e.g., tool name)
     - `input`: Data to check (message text, tool parameters)
     - `output`: Response data (for post-stage)

3. **Control Evaluation**
   - Hook sends Step to AgentControl server
   - Server finds matching controls using `scope.step_types` and `scope.step_names`
   - Evaluators run (regex, LLM, custom logic)
   - Server returns evaluation result

4. **Decision Enforcement**
   - If `is_safe=True`: Execution continues normally
   - If `is_safe=False`: Hook raises `ControlViolationError`
   - Strands catches error and triggers retry (if configured)
   - Retry includes guidance from control (e.g., "Remove PII")

## Configuration Patterns

### Pattern 1: Basic LLM Safety

Monitor only model input/output (most common):

```python
hook = AgentControlHook(
    agent_name="chatbot",
    event_control_list=[
        BeforeInvocationEvent,    # User input
        AfterModelCallEvent,      # Model output
    ]
)
```

**Controls needed:**
```python
[
    {"scope": {"step_types": ["llm"], "stages": ["pre"]}},   # Input safety
    {"scope": {"step_types": ["llm"], "stages": ["post"]}},  # Output safety
]
```

### Pattern 2: LLM + Tool Safety

Add tool validation:

```python
hook = AgentControlHook(
    agent_name="support-agent",
    event_control_list=[
        BeforeInvocationEvent,
        AfterModelCallEvent,
        BeforeToolCallEvent,     # + Tool input validation
    ]
)
```

**Controls needed:**
```python
[
    {"scope": {"step_types": ["llm"], "stages": ["pre"]}},
    {"scope": {"step_types": ["llm"], "stages": ["post"]}},
    {"scope": {"step_types": ["tool"], "step_names": ["lookup_order"], "stages": ["pre"]}},
    {"scope": {"step_types": ["tool"], "step_names": ["search_kb"], "stages": ["pre"]}},
]
```

### Pattern 3: Custom Violation Handling

Add custom logic when violations occur:

```python
def alert_security_team(violation_info, result):
    if violation_info['stage'] == 'pre':
        send_alert(f"Blocked malicious input: {violation_info['reason']}")

hook = AgentControlHook(
    agent_name="production-agent",
    on_violation_callback=alert_security_team
)
```

## Benefits of Hook-Based Integration

### 1. Zero Code Modification
- No decorators on tools
- No manual safety checks in agent code
- Hook handles everything automatically

### 2. Unified Mechanism
- Same hook for LLM and tool controls
- Single configuration point
- Consistent error handling

### 3. Flexible Targeting
- General controls: `step_types=["llm"]` applies everywhere
- Specific controls: `step_types=["tool"], step_names=["lookup_order"]` targets one tool
- Mix and match as needed

### 4. Real-Time Updates
- Controls stored on server
- Update control configuration without redeploying agent
- Changes take effect immediately

### 5. Complete Observability
- Every check logged
- Violations tracked with context
- Full audit trail for compliance

## Usage Examples

### Example 1: Block PII in User Input

**Control:**
```python
{
    "name": "block-pii-input",
    "scope": {"step_types": ["llm"], "stages": ["pre"]},
    "evaluator": {
        "name": "regex",
        "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}
    },
    "action": {"decision": "deny"}
}
```

**Result:** Any SSN in user input blocked before reaching LLM.

### Example 2: Validate Order ID Format

**Control:**
```python
{
    "name": "validate-order-id",
    "scope": {
        "step_types": ["tool"],
        "step_names": ["lookup_order"],
        "stages": ["pre"]
    },
    "selector": {"path": "input.order_id"},  # Extract order_id parameter
    "evaluator": {
        "name": "regex",
        "config": {"pattern": r"ORD-.*[A-Za-z]"}  # Detect invalid format
    },
    "action": {"decision": "deny"}
}
```

**Result:** Invalid order IDs blocked before `lookup_order` tool executes.

### Example 3: Prevent SQL Injection

**Control:**
```python
{
    "name": "prevent-sql-injection",
    "scope": {
        "step_types": ["tool"],
        "step_names": ["search_knowledge_base"],
        "stages": ["pre"]
    },
    "selector": {"path": "input.query"},
    "evaluator": {
        "name": "regex",
        "config": {
            "pattern": r"(SELECT|DROP|UNION|INSERT|--|;|')"
        }
    },
    "action": {"decision": "deny"}
}
```

**Result:** SQL injection attempts blocked before search executes.

## Best Practices

### 1. Initialize AgentControl First
Always call `agent_control.init()` before creating hooks:
```python
agent_control.init(agent_name="my-agent", agent_id="...")
hook = AgentControlHook(agent_name="my-agent")  # Must match init()
```

### 2. Choose Events Strategically
Only monitor events you need:
- Simple chatbot → `[BeforeInvocationEvent, AfterModelCallEvent]`
- Tool-heavy agent → Add `[BeforeToolCallEvent]`
- Multi-agent system → Add `[BeforeNodeCallEvent, AfterNodeCallEvent]`

### 3. Use Descriptive Control Names
Good: `"block-pii-input"`, `"validate-order-id-format"`
Bad: `"control1"`, `"check"`

### 4. Test Both Stages
- Pre-stage: Block bad input before processing
- Post-stage: Block bad output before user sees it

### 5. Leverage step_names for Granularity
- General rule → Use only `step_types`
- Tool-specific rule → Add `step_names`

## Common Scenarios

### Adding a New Tool with Validation

1. **Create the tool:**
```python
@tool
async def delete_record(record_id: str) -> str:
    # Delete logic
    return f"Deleted {record_id}"
```

2. **Create control for the tool:**
```python
{
    "name": "prevent-dangerous-deletes",
    "scope": {
        "step_types": ["tool"],
        "step_names": ["delete_record"],
        "stages": ["pre"]
    },
    "selector": {"path": "input.record_id"},
    "evaluator": {
        "name": "regex",
        "config": {"pattern": r"(admin|root|system)"}
    },
    "action": {"decision": "deny"}
}
```

3. **That's it!** Hook automatically validates delete_record calls.

### Updating a Control Without Redeployment

```bash
# Update control configuration via API
curl -X PUT http://localhost:8000/api/v1/controls/5/data \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "evaluator": {
      "name": "regex",
      "config": {"pattern": "NEW_PATTERN"}
    }
  }'

# Changes take effect immediately for all agents!
```

## Troubleshooting

### Hook not triggering
- Check: `agent_control.init()` called before hook creation?
- Check: Server running? (`curl http://localhost:8000/health`)
- Check: Hook in agent's hooks list?

### Controls not matching
- Check: Control scope matches step type? (`step_types=["llm"]` vs `["tool"]`)
- Check: Tool name spelled correctly in `step_names`?
- Check: Control enabled? (`"enabled": true`)

### Too many retries
- Adjust `max_retries` parameter:
  ```python
  hook = AgentControlHook(agent_name="my-agent", max_retries=5)
  ```

## Next Steps

- **See it in action:** Run the [interactive demo](../interactive_demo/)
- **Explore the code:** Review [agent_control_hook.py](agent_control_hook.py)
- **Build your own:** Use these patterns in your production agents

---

**The marriage of hooks and controls provides automatic, flexible, and maintainable safety for AI agents without modifying your application code.**
