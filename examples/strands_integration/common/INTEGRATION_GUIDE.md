# Integration Guide - Concepts

Deep dive into how AgentControl integrates with Strands agents.

## Core Concepts

### What is a Hook?

A **hook** intercepts Strands agent lifecycle events:
- `BeforeInvocationEvent` - User message arrives
- `BeforeModelCallEvent` - About to call LLM
- `AfterModelCallEvent` - LLM responded
- `BeforeToolCallEvent` - About to execute tool
- `AfterToolCallEvent` - Tool completed

Hooks inject safety checks without modifying agent code.

### What is a Control?

A **control** defines a safety rule with 4 components:

1. **What to check**: Input/output/tool parameters
2. **When to check**: Pre-stage (before) or post-stage (after)
3. **How to check**: Regex, LLM, custom evaluator
4. **What to do**: Allow, deny, warn, log

Example:
```python
{
    "scope": {"step_types": ["llm"], "stages": ["pre"]},
    "evaluator": {"name": "regex", "config": {"pattern": "SSN_PATTERN"}},
    "action": {"decision": "deny"}
}
```

### How They Work Together

```
User: "My SSN is 123-45-6789"
  ↓
Strands: BeforeInvocationEvent fired
  ↓
Hook: Extract text → Create Step(type="llm", input="...")
  ↓
Server: Find matching controls → Run evaluators → Pattern match!
  ↓
Server: Return is_safe=False
  ↓
Hook: Raise ControlViolationError → Block execution
```

## Control Types

### LLM Controls (General)

Apply to **all** model interactions:
```python
{"scope": {"step_types": ["llm"], "stages": ["pre"]}}
```

Use for: PII blocking, toxic language, hallucination detection

### Tool Controls (Specific)

Target **individual tools** by name:
```python
{
    "scope": {
        "step_types": ["tool"],
        "step_names": ["lookup_order"],
        "stages": ["pre"]
    }
}
```

Use for: Input validation, SQL injection prevention, business rules

**Key**: Hook extracts tool name from event → Server matches `step_names` → Control applies automatically

## Data Flow

1. **Event** → Strands fires (e.g., BeforeToolCallEvent)
2. **Extract** → Hook gets tool_name="lookup_order", input={...}
3. **Step** → Hook creates Step(type="tool", name="lookup_order", ...)
4. **Evaluate** → Server runs matching controls
5. **Enforce** → Hook blocks if unsafe

## Configuration Patterns

**Pattern 1: LLM Safety Only**
```python
hook = AgentControlHook(
    agent_name="chatbot",
    event_control_list=[
        BeforeInvocationEvent,
        AfterModelCallEvent
    ]
)
```

**Pattern 2: LLM + Tool Safety**
```python
hook = AgentControlHook(
    agent_name="support-agent",
    event_control_list=[
        BeforeInvocationEvent,
        AfterModelCallEvent,
        BeforeToolCallEvent  # Add tool validation
    ]
)
```

**Pattern 3: Custom Violation Handler**
```python
def alert_on_violation(violation_info, result):
    send_alert(f"Blocked: {violation_info['reason']}")

hook = AgentControlHook(
    agent_name="prod-agent",
    on_violation_callback=alert_on_violation
)
```

## Benefits

1. **Zero Code Changes** - No decorators on tools
2. **Unified Mechanism** - Same hook for all controls
3. **Flexible Targeting** - General or tool-specific
4. **Real-Time Updates** - Change controls without redeploying
5. **Complete Audit Trail** - Every check logged

## Best Practices

1. Initialize first: `agent_control.init()` before `AgentControlHook()`
2. Choose events strategically: Only monitor what you need
3. Use descriptive names: `"block-pii-input"` not `"control1"`
4. Test both stages: Pre (block bad input) and post (block bad output)
5. Tool-specific when needed: Use `step_names` for granular control

## Common Scenarios

### New Tool with Validation

1. Create tool function
2. Define control with `step_names=["tool_name"]`
3. Done! Hook handles validation automatically

### Update Control Without Redeploy

```bash
curl -X PUT http://localhost:8000/api/v1/controls/5/data \
  -d '{"evaluator": {"config": {"pattern": "NEW_PATTERN"}}}'

# Takes effect immediately
```

---

For usage examples, see [main README](../README.md) or run the demos.
