# AgentControl + Strands Integration

Automatic safety controls for AWS Strands agents using hooks - no decorators needed.

## Quick Start

**Prerequisites:** Python 3.12+, OpenAI API key, AgentControl server

```bash
# 1. Install
cd examples/strands_integration
uv pip install -e .

# 2. Configure
cp .env.example .env
# Edit .env: Add OPENAI_API_KEY and AGENT_CONTROL_URL

# 3. Start server (Terminal 1)
curl -fsSL https://raw.githubusercontent.com/agentcontrol/agent-control/docker-compose.yml | docker compose -f - up -d

# 4. Setup controls (Terminal 2)
cd examples/strands_integration/interactive_demo
uv run setup_interactive_controls.py

# 5. Run demo (Terminal 3)
streamlit run interactive_support_demo.py
```

Open http://localhost:8501 and click test buttons to see safety controls in action.

## Available Demos

### [Interactive Demo](interactive_demo/)
Customer support agent with PII blocking and SQL injection prevention. Shows real-time safety checks in Streamlit UI.

### [Steering Demo](steering_demo/)
Banking email agent with PII redaction. Combines AgentControl Hook (deny on tool calls) + Strands Steering (steer on LLM draft) for layered governance. Uses a two-phase draft → send flow so steer can guide before tool calls.

## How It Works

**AgentControlHook** = Automatic safety without code changes

```python
from agent_control.integrations.strands import AgentControlHook
from strands import Agent

# Initialize
import agent_control
agent_control.init(agent_name="my-customer-agent")

# Create hook
hook = AgentControlHook(agent_name="my-customer-agent")

# Attach to agent - done!
agent = Agent(
    model=model,
    system_prompt="...",
    tools=[...],
    hooks=[hook]  # All safety checks automated
)
```

**Hook intercepts events** → **Server evaluates controls** → **Blocks unsafe actions**

For steer actions, the steering handler converts AgentControl steer into a Strands `Guide()` retry.

## Controls

**LLM Controls** - Apply to all model interactions:
```python
{
    "scope": {"step_types": ["llm"], "stages": ["pre"]},
    "evaluator": {"name": "regex", "config": {"pattern": r"\d{3}-\d{2}-\d{4}"}},
    "action": {"decision": "deny"}
}
```

**Tool Controls** - Target specific tools:
```python
{
    "scope": {
        "step_types": ["tool"],
        "step_names": ["lookup_order"],  # Only this tool
        "stages": ["pre"]
    },
    "evaluator": {"name": "regex", "config": {"pattern": r"ORD-\d+"}},
    "action": {"decision": "deny"}
}
```

Hook automatically extracts tool names from events - no decorators needed!

## Architecture

```
User Input
  ↓
Strands fires event (BeforeToolCallEvent, AfterModelCallEvent, etc.)
  ↓
AgentControlHook intercepts → Creates Step → Calls AgentControl server
  ↓
Server evaluates controls → Returns safe/unsafe
  ↓
Hook enforces decision: Continue ✅ or Block ❌
```

## Integration Patterns

**Basic setup**:
```python
hook = AgentControlHook(
    agent_name="my-customer-agent",
    enable_logging=True
)
```

**Steering integration**:
- `AgentControlHook` for tool-stage deny (hard blocks)
- `AgentControlSteeringHandler` for LLM steer → `Guide()` (corrective guidance)

See `steering_demo/README.md` for complete implementation.

## Troubleshooting

**"AgentControl not initialized"**
- Run `agent_control.init()` before creating hook

**Controls not triggering**
- Server running? `curl http://localhost:8000/health`
- Controls exist? Re-run `setup_*_controls.py`

**Import errors**
- Install deps: `uv sync` or `pip install -e .`

## Files

- `interactive_demo/` - Customer support demo with PII/SQL injection blocking
- `steering_demo/` - Banking email demo with PII redaction
