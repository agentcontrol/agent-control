# Agent Control Demo

End-to-end workflow: create controls, run a controlled agent, and update controls dynamically without redeploying.

## What this example shows

- Server-side control creation
- Direct control association to an agent
- Blocking unsafe inputs and outputs
- Updating controls in place

## Quick run

```bash
# From repo root
make server-run

# In a separate shell
uv run python examples/agent_control_demo/setup_controls.py
uv run python examples/agent_control_demo/demo_agent.py
```

Full walkthrough: https://docs.agentcontrol.dev/examples/agent-control-demo
