# Customer Support Agent

Enterprise support flow with PII protection, prompt-injection defense, and multiple tools.

## What this example shows

- Agent registration and control configuration
- Tool-specific controls and staged evaluation
- Interactive support workflow

## Quick run

```bash
# From repo root
make server-run

# In a separate shell
cd examples/customer_support_agent
uv run python setup_demo_controls.py
uv run python run_demo.py
```

Full walkthrough: https://docs.agentcontrol.dev/examples/customer-support
