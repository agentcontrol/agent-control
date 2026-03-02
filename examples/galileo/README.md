# Galileo Luna-2 Integration Examples

This directory contains examples demonstrating Agent Control integration with Galileo's Luna-2 Protect service for real-time toxicity detection and content moderation.

## Luna-2 Demo (`luna2_demo.py`)

Demonstrates using the Luna-2 evaluator with a **CENTRAL stage** for toxicity detection.

### Prerequisites

1. **Galileo API Key**: Get yours from [Galileo Console](https://console.galileo.ai)
2. **Galileo Project**: Create a project and stage in the Galileo Console
3. **Agent Control**: Install with Luna-2 support

### Setup

```bash
# 1. Export your Galileo API key
export GALILEO_API_KEY="your-api-key-here"

# 2. (Optional) Set custom console URL
export GALILEO_CONSOLE_URL="https://console.demo-v2.galileocloud.io"

# 3. (Optional) Override project/stage names
export GALILEO_PROJECT_NAME="protect-demo"
export GALILEO_STAGE_NAME="luna2-toxicity-stage"

# 4. Install deps and run the demo
cd examples/galileo
uv sync
uv run luna2_demo.py
```

### What it Does

The demo tests various inputs against a pre-configured toxicity detection stage:
- ✅ Safe greetings and questions pass through
- 🚫 Toxic content gets blocked
- 📊 Toxicity scores are displayed for each input
- 🔗 Trace IDs link to detailed analysis in Galileo Console

### Central vs Local Stages

- **Central Stage** (used in this demo): Rulesets and policies are pre-configured on the Galileo server. Simply reference the stage by name.
- **Local Stage**: Define rulesets at runtime in your code (see evaluator documentation).

### Expected Output

```
============================================================
Luna-2 Central Stage Demo - Toxicity Detection
============================================================

📌 Console URL: https://console.demo-v2.galileocloud.io
📌 API Key: gp_abc123...xyz
📌 Project: protect-demo
📌 Stage: luna2-toxicity-stage

------------------------------------------------------------
Testing toxicity detection with Central Stage...
------------------------------------------------------------

📝 Safe greeting
   Input: "Hello, how can I help you?"
   Result: ✅ PASSED
   Toxicity: [░░░░░░░░░░] 2.0%
   Trace: 7a3f9d2b...

📝 Toxic message
   Input: "You are so stupid and I hate you!"
   Result: 🚫 BLOCKED
   Toxicity: [████████░░] 85.0%
   Trace: 9c4e1a5f...
```

### Troubleshooting

- **"GALILEO_API_KEY environment variable is required"**: Export your API key
- **"Project not found"**: Set `GALILEO_PROJECT_NAME` to match your Galileo project
- **"Stage not found"**: Set `GALILEO_STAGE_NAME` to match a stage in your project
- **Import errors**: Ensure you installed with `[galileo]` extra: `pip install agent-control-evaluators[galileo]`

### Documentation

- [Galileo Protect Overview](https://v2docs.galileo.ai/concepts/protect/overview)
- [Luna-2 Python API Reference](https://v2docs.galileo.ai/sdk-api/python/reference/protect)
- [Agent Control Luna-2 Evaluator](../../evaluators/extra/galileo/)

