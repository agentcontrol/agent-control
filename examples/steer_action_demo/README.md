# Steer Action Demo

Banking transfer agent showcasing allow, deny, warn, and steer actions.

## What this example shows

- Steer actions with corrective guidance
- Multi-step approval workflows
- Deterministic retry behavior

## Quick run

```bash
# From repo root
export OPENAI_API_KEY="your-key-here"
make server-run

# In separate shell
cd examples/steer_action_demo
uv pip install -e . --upgrade
uv run python setup_controls.py
uv run python autonomous_agent_demo.py
```

Full walkthrough: https://docs.agentcontrol.dev/examples/steer-action-demo
