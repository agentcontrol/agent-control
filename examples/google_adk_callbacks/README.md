# Google ADK Callbacks

Model and tool guardrails via ADK's native callback hooks.

## What this example shows

- Pre-model prompt injection blocking
- Pre-tool and post-tool output filtering
- Fail-closed behavior on server errors

## Quick run

```bash
# From repo root
make server-run
export GOOGLE_API_KEY="your-key-here"

cd examples/google_adk_callbacks
uv pip install -e . --upgrade
uv run python setup_controls.py
uv run adk run my_agent
```

Full walkthrough: https://docs.agentcontrol.dev/examples/google-adk-callbacks
