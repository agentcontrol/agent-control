# AgentControl + AWS Strands Integration

## Overview

AgentControl integrates with AWS Strands Agents using **hook-based architecture**, leveraging Strands' native `HookProvider` system to intercept agent lifecycle events and apply safety controls.

## Integration Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│                     Strands Agent Execution                     │
└────────────┬────────────────────────────────────────────────────┘
             │
             ├─► LLM Call Start
             │   └─► BeforeModelCallEvent (optional pre-check)
             │
             ├─► LLM Response Received
             │   └─► AfterModelCallEvent
             │       └─► AgentControl Post-Evaluation
             │           ├─ PII Detection
             │           ├─ Hallucination Detection
             │           ├─ Toxicity Filtering
             │           └─► [PASS → Continue | BLOCK → Retry]
             │
             ├─► Tool Call Requested
             │   └─► BeforeToolInvocationEvent
             │       └─► AgentControl Pre-Evaluation
             │           └─► [PASS → Execute | BLOCK → Error]
             │
             ├─► Tool Response Received
             │   └─► AfterToolInvocationEvent
             │       └─► AgentControl Post-Evaluation
             │           └─► [PASS → Continue | BLOCK → Error]
             │
             └─► Agent Completion
                 └─► AfterInvocationEvent (statistics logging)
```

## Core Integration Code

### 1. AgentControl Hook Provider

```python
from strands.hooks import HookProvider
from strands.hooks.events import AfterModelCallEvent
import agent_control

class AgentControlHookProvider(HookProvider):
    async def on_after_model_call(self, event: AfterModelCallEvent):
        # Create AgentControl step
        step = Step(
            type="llm",
            name="assistant",
            input=event.input,
            output=event.output,
            context={"model": event.model_id}
        )

        # Run safety check
        result = await agent_control.check(step=step, stage="post")

        if not result.is_safe:
            # Option 1: Retry with guidance (recommended)
            event.retry = True
            event.retry_guidance = f"Blocked: {result.reason}"

            # Option 2: Raise exception to halt
            # raise ControlViolationError(result.reason)
```

### 2. Agent Initialization

```python
from strands import Agent
from strands.models.openai import OpenAIModel

# Initialize AgentControl
agent_control.init(
    agent_name="my-agent",
    controls=[
        {
            "name": "block-pii",
            "check_stage": "post",
            "applies_to": "llm_call",
            "evaluator": {
                "name": "luna2-evaluator",
                "config": {
                    "metric": "pii_detection",
                    "operator": "gt",
                    "target_value": 0.7,
                }
            },
            "action": {"decision": "deny"}
        }
    ]
)

# Create Strands agent with hook
agent = Agent(
    model=OpenAIModel("gpt-4o"),
    hooks=[AgentControlHookProvider()],  # ← Safety integration
)
```

## Example Provided

### **Interactive Demo** ([interactive_demo/](./interactive_demo/))
- Live Streamlit application demonstrating real-time safety protection
- Multi-agent customer support system (triage → general/technical support)
- Pre-loaded attack prompts to test PII detection
- Visual feedback showing violations as they happen
- PII detection using regex evaluator (SSN, credit cards, emails)
- Complete integration with AgentControl server and policies

## Key Benefits

### 1. **Transparent Integration**
- No changes to agent business logic
- Safety controls defined separately
- Hooks attach automatically

### 2. **Multi-Agent Support**
- Controls apply across entire graph
- Per-agent statistics available
- Works with Graph and Swarm patterns

### 3. **Flexible Evaluation**
- Pre-evaluation (before LLM/tool execution)
- Post-evaluation (after responses)
- Local or server-side evaluation

### 4. **Strands-Native Features**
- Uses Strands' retry mechanism (`event.retry = True`)
- Integrates with OTEL tracing
- Works with all Strands model providers

## Evaluation Flow

```python
# Pre-evaluation (optional)
BeforeToolInvocationEvent
    ↓
Check tool parameters
    ↓
[Block unsafe tool calls]

# Post-evaluation (recommended)
AfterModelCallEvent / AfterToolInvocationEvent
    ↓
Check LLM/tool output
    ↓
If unsafe:
    - Set event.retry = True
    - Provide retry_guidance
    - Agent regenerates response
    ↓
If safe:
    - Continue execution
```

## Observability Integration

### Strands OTEL Traces
```python
from strands.telemetry import StrandsTelemetry

telemetry = StrandsTelemetry(
    endpoint="https://console.galileo.ai/api/v2/otlp/traces",
    headers={"Authorization": f"Bearer {key}"}
)
```

### AgentControl Control Spans
```python
from agent_control.observability import get_cached_control_spans

# After execution, control spans are cached
control_spans = get_cached_control_spans()

# Automatically sent to Galileo with Strands traces
```

### Unified View in Galileo
- Agent spans (Strands)
- Control execution spans (AgentControl)
- LLM call details
- Tool invocations
- Safety decisions

## Production Checklist

### Performance
- [ ] Use local Luna-2 evaluators for common checks (PII, toxicity)
- [ ] Configure appropriate timeout_ms for each control
- [ ] Test latency impact on critical paths

### Reliability
- [ ] Set `on_error: "allow"` for fail-open behavior (availability)
- [ ] Set `on_error: "deny"` for fail-closed behavior (safety)
- [ ] Test error handling and retry logic

### Monitoring
- [ ] Enable OTEL tracing in Strands
- [ ] Configure Galileo project for control logs
- [ ] Set up alerts for high block rates
- [ ] Monitor evaluation latencies

### Testing
- [ ] Test normal queries (should pass)
- [ ] Test PII leakage (should block)
- [ ] Test prompt injection (should block)
- [ ] Test hallucinations (should block/retry)
- [ ] Test multi-agent coordination

## Cost Considerations

| Component | Cost | Notes |
|-----------|------|-------|
| **Strands LLM calls** | OpenAI API pricing | Per token, model-specific |
| **Luna-2 evaluator** | Galileo Luna-2 pricing | Per evaluation |
| **OTEL traces** | Storage cost | Negligible for spans |
| **AgentControl server** | Self-hosted or SaaS | Optional, for centralized controls |

**Optimization tips:**
- Cache evaluation results when possible
- Tune confidence thresholds to reduce over-blocking
- Use local evaluators to avoid network latency
- Batch multiple checks when feasible

## Common Patterns

### Pattern 1: Retry on Safety Violation
```python
async def on_after_model_call(self, event):
    result = await agent_control.check(...)
    if not result.is_safe:
        event.retry = True  # Strands regenerates
        event.retry_guidance = f"Fix: {result.reason}"
```

### Pattern 2: Halt on Critical Violation
```python
async def on_after_model_call(self, event):
    result = await agent_control.check(...)
    if not result.is_safe and result.confidence > 0.9:
        raise ControlViolationError(result.reason)
```

### Pattern 3: Per-Agent Controls
```python
# Different hooks for different agents
triage_hook = AgentControlHookProvider(
    agent_name="triage",
    controls=["prompt-injection"]
)

kb_hook = AgentControlHookProvider(
    agent_name="kb",
    controls=["pii-detection"]
)
```

## Troubleshooting

### Issue: Controls not firing
**Cause:** Hook not registered or event not triggered
**Fix:** Verify `hooks=[...]` passed to Agent constructor

### Issue: High latency
**Cause:** Network evaluation or inefficient controls
**Fix:** Use local Luna-2, tune timeout_ms, reduce control count

### Issue: False positives
**Cause:** Confidence threshold too low
**Fix:** Increase `target_value` in control config

### Issue: Missing observability data
**Cause:** OTEL not configured or spans not captured
**Fix:** Enable StrandsTelemetry, verify Galileo API key

## Resources

- [Strands Agents Documentation](https://strandsagents.com/latest/documentation/)
- [Strands Hooks API](https://strandsagents.com/latest/documentation/docs/api-reference/python/agent/agent/)
- [AgentControl Documentation](../../README.md)
- [Galileo Luna-2](https://www.galileo.ai/docs/luna-2)
- [Multi-Agent Patterns](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/multi-agent/)

## Next Steps

1. **Run the demo**: Try the [Interactive Demo](./interactive_demo/) to see AgentControl in action
2. **Test attack prompts**: Use pre-loaded examples to see real-time blocking
3. **Custom controls**: Define your own evaluators and policies
4. **Deploy**: Set up AgentControl server for centralized management
5. **Integrate**: Adapt the patterns from the demo for your own multi-agent systems
