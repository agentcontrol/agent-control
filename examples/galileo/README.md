# Galileo Luna-2 Example

Toxicity detection and content moderation with Galileo Protect.

## What this example shows

- Luna-2 evaluator integration
- Environment-based configuration
- End-to-end evaluation flow

## Quick run

```bash
# In repo root
export GALILEO_API_KEY="your-api-key"
make server-run

# In a separate shell
cd examples/galileo
uv pip install -e . --upgrade
uv run python luna2_demo.py
```

Full walkthrough: https://docs.agentcontrol.dev/examples/galileo-luna2
