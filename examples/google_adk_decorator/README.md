# Google ADK Decorator

`@control()` decorator pattern for tool protection inside a Google ADK app.

## What this example shows

- `@control()` on ADK tool functions
- Automatic step registration from decorators
- Optional sdk-local execution mode

## Quick run

```bash
# From repo root
make server-run
export GOOGLE_API_KEY="your-key-here"

cd examples/google_adk_decorator
uv pip install -e . --upgrade
uv run python setup_controls.py
uv run adk run my_agent
```

Full walkthrough: https://docs.agentcontrol.dev/examples/google-adk-decorator
