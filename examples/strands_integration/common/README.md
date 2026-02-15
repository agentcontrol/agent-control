# AgentControl Hook for Strands

Reusable hook for integrating AgentControl safety checks with AWS Strands agents.

## Quickstart: Run the Interactive Demo

**See AgentControl in action in under 5 minutes:**

### 1. Install Dependencies
```bash
cd examples/strands_integration
uv sync  # or: pip install -e .
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env and add:
#   OPENAI_API_KEY=your_key_here
#   AGENT_CONTROL_URL=http://localhost:8000
```

### 3. Start AgentControl Server
```bash
# Terminal 1
cd server
make run
```

### 4. Setup Controls
```bash
# Terminal 2
cd examples/strands_integration/interactive_demo
python setup_interactive_controls.py
```

You should see:
```
✅ Ready to run demo

Controls created:
  • block-pii-input (LLM, pre-stage)
  • block-pii-output (LLM, post-stage)
  • validate-order-id-format (Tool: lookup_order)
  • prevent-sql-injection-kb-query (Tool: search_knowledge_base)
```

### 5. Launch the Demo
```bash
# Terminal 3
cd examples/strands_integration/interactive_demo
streamlit run interactive_support_demo.py
```

Open http://localhost:8501 in your browser.

### 6. Try It Out

Click the example buttons:
- **✅ Valid Order** - Normal conversation, checks pass
- **❌ PII Detected** - SSN in input, will be blocked by LLM control
- **❌ SQL Injection** - SQL injection attempt, will be blocked by tool control

Watch the console (Terminal 3) to see tool interception and control evaluation!

---

## AgentControl Integration

### What is it?

The `AgentControlHook` automatically integrates safety controls into your Strands agents:

- **Hooks** intercept agent lifecycle events (model calls, tool calls, etc.)
- **Controls** define safety rules (block PII, validate inputs, prevent SQL injection)
- **Hook + Controls** = Automatic safety without modifying your agent code

### How It Works

```
User Input
    ↓
Strands Agent fires event (BeforeModelCallEvent, BeforeToolCallEvent, etc.)
    ↓
AgentControlHook intercepts event
    ↓
Hook extracts data and creates Step
    ↓
Hook calls AgentControl server to evaluate controls
    ↓
Server returns: Safe ✅ or Unsafe ❌
    ↓
If safe: Continue normally
If unsafe: Block or retry with guidance
```

### Basic Usage

```python
from common import AgentControlHook
from strands import Agent
from strands.models.openai import OpenAIModel

# Initialize AgentControl first
import agent_control
agent_control.init(agent_name="my-agent", agent_id="...")

# Create hook
hook = AgentControlHook(agent_name="my-agent")

# Attach to agent
agent = Agent(
    model=OpenAIModel(model_id="gpt-4o-mini"),
    system_prompt="You are a helpful assistant",
    hooks=[hook]  # That's it!
)
```

The hook automatically:
- Monitors all agent events
- Sends data to AgentControl for evaluation
- Blocks unsafe operations
- Retries with guidance when violations occur

### Monitor Specific Events

```python
from strands.hooks import BeforeModelCallEvent, AfterModelCallEvent

# Only check LLM input/output (most common)
hook = AgentControlHook(
    agent_name="my-agent",
    event_control_list=[BeforeModelCallEvent, AfterModelCallEvent]
)
```

### Configuration

```python
hook = AgentControlHook(
    agent_name="my-agent",              # Required: Agent identifier
    max_retries=3,                      # Max retry attempts
    event_control_list=[...],           # Events to monitor (None = all)
    on_violation_callback=my_handler,   # Custom violation handler
    enable_logging=True                 # Print execution logs
)
```

### Two Types of Controls

**1. LLM Controls** - Apply to all model interactions:
```python
{
    "scope": {"step_types": ["llm"], "stages": ["pre"]},  # Check LLM input
    "evaluator": {"name": "regex", "config": {"pattern": r"\d{3}-\d{2}-\d{4}"}},
    "action": {"decision": "deny"}
}
```

**2. Tool-Specific Controls** - Target specific tools:
```python
{
    "scope": {
        "step_types": ["tool"],
        "step_names": ["lookup_order"],  # Only this tool!
        "stages": ["pre"]
    },
    "evaluator": {"name": "regex", "config": {"pattern": r"ORD-.*[A-Za-z]"}},
    "action": {"decision": "deny"}
}
```

The hook automatically extracts tool names from events, so controls can target specific tools without decorators.

## Troubleshooting

**"AgentControl not initialized"**
- Initialize before creating hook: `agent_control.init(...)` then `hook = AgentControlHook(...)`

**Controls not triggering**
- Check server is running: `curl http://localhost:8000/health`
- Verify controls exist: `python setup_interactive_controls.py`

**"Unknown event type"**
- Use valid Strands events: `BeforeModelCallEvent`, `AfterModelCallEvent`, etc.

## Learn More

- **[INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)** - Detailed concepts: what are hooks, controls, and how they integrate
- **[Interactive Demo](../interactive_demo/)** - Complete example with PII blocking and tool validation
- **[Steering Demo](../steering_demo/)** - Layered governance with AgentControl + Steering
