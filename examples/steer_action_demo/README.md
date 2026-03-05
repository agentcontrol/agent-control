# Steer Action Demo

Banking transfer agent showcasing allow, deny, warn, and steer actions.

## Quick run

```bash
# From repo root
make server-run
export OPENAI_API_KEY="your-key-here"

cd examples/steer_action_demo
uv run pip install -e . --upgrade
uv run python setup_controls.py
uv run python autonomous_agent_demo.py
```

Full walkthrough: [Steer Action Demo](https://docs.agentcontrol.dev/examples/steer-action-demo)
