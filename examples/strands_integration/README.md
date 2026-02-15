# AgentControl + Strands Integration Examples

Interactive demonstrations of AgentControl integrated with AWS Strands agents.

## Overview

These examples show how to integrate AgentControl's safety controls with Strands-based agents using hooks. The hook-based architecture provides automatic safety enforcement without modifying your agent code.

## Available Demos

### [Interactive Demo](interactive_demo/)
Real-time safety demonstration with Streamlit UI showing PII blocking and tool validation.

### [Steering Demo](steering_demo/)
Layered governance combining AgentControl (safety) with Strands Steering (quality).

## Quick Start

### Prerequisites

- Python 3.11+
- OpenAI API key
- AgentControl server running

### Installation

```bash
cd examples/strands_integration

# Install dependencies
uv sync  # or: pip install -e .

# Configure environment
cp .env.example .env
# Edit .env and add your API keys:
#   OPENAI_API_KEY=your_key_here
#   AGENT_CONTROL_URL=http://localhost:8000
```

### Running the Interactive Demo

**Terminal 1 - Start the AgentControl server:**
```bash
cd server
make run
```

**Terminal 2 - Setup controls:**
```bash
cd examples/strands_integration/interactive_demo
python setup_interactive_controls.py
```

You should see output confirming controls were created:
```
✓ Created 4 interactive demo control(s)
✅ Interactive Support Demo Ready
```

**Terminal 3 - Launch the demo:**
```bash
cd examples/strands_integration/interactive_demo
streamlit run interactive_support_demo.py
```

The app will open in your browser at `http://localhost:8501`

## Using the Demo

### Test Normal Conversation

Try safe prompts:
- "What's your return policy?"
- "I need help with my order ORD-12345"

Watch the safety checks pass in the sidebar.

### Test Safety Controls

Click the example buttons:

**✅ Valid Order** - Normal tool usage, should succeed
**❌ PII Detected** - Contains SSN, will be blocked by LLM control
**❌ SQL Injection** - SQL injection attempt, will be blocked by tool control

Watch the console (Terminal 3) for detailed logs showing:
- Tool interception
- Control evaluation
- Block/allow decisions

### Understanding the Output

**In the UI:**
- Green checkmarks (✅) = Safety checks passed
- Red violations (🚫) = Blocked content with details

**In the console:**
- `🔧 TOOL CALL INTERCEPTED` = Hook captured tool call
- `✅ All checks passed` = Controls allowed the action
- `🚫 VIOLATION DETECTED` = Controls blocked the action

## Architecture

```
User Input
    ↓
AgentControlHook (intercepts events)
    ├─ BeforeInvocationEvent → Check user input
    ├─ BeforeToolCallEvent → Validate tool parameters
    ├─ AfterModelCallEvent → Check agent output
    └─ AfterToolCallEvent → Filter tool results
    ↓
AgentControl Server (evaluates controls)
    ├─ LLM Controls (step_types=["llm"])
    └─ Tool Controls (step_types=["tool"], step_names=["tool_name"])
    ↓
Safe Output to User
```

## How It Works

### Hooks
A **hook** is an event interceptor that watches agent lifecycle events (model calls, tool calls, etc.) and triggers safety checks at the right moments.

### Controls
A **control** is a safety rule (like "block PII") that evaluates data and decides whether to allow or block an action.

### Integration
The `AgentControlHook` connects Strands events to AgentControl:
1. Strands fires events (BeforeModelCallEvent, BeforeToolCallEvent, etc.)
2. Hook extracts relevant data and creates a `Step` object
3. Hook calls AgentControl to evaluate controls for that step
4. If unsafe, hook triggers a retry or blocks the action
5. If safe, execution continues normally

For detailed integration patterns, see [INTEGRATION_GUIDE.md](common/INTEGRATION_GUIDE.md)

## Troubleshooting

### "AgentControl not initialized"
Server not running or not accessible.

**Solution:**
```bash
# Check server health
curl http://localhost:8000/health

# Restart if needed
cd server && make run
```

### No controls triggering
Controls not set up.

**Solution:**
```bash
# Re-run setup
python examples/strands_integration/interactive_demo/setup_interactive_controls.py

# Verify controls exist
curl http://localhost:8000/api/v1/controls | jq '.controls[].name'
```

### Import errors
Dependencies not installed.

**Solution:**
```bash
cd examples/strands_integration
uv sync  # or: pip install -e .
```

## Next Steps

1. **Understand the integration** - Read [INTEGRATION_GUIDE.md](common/INTEGRATION_GUIDE.md) for architectural details
2. **Modify controls** - Edit `setup_interactive_controls.py` to add your own safety rules
3. **Extend the demo** - Add new tools and controls to test different scenarios
4. **Build your own** - Use the hook pattern in your production agents

## Support

For questions or issues, see the [common/README.md](common/README.md) documentation or open an issue on GitHub.
