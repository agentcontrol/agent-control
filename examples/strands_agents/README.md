# AWS Strands Example

Guardrails for AWS Strands agent workflows and tool calls.

## What this example shows

- Integration points for Strands agents
- Control configuration patterns
- Runtime evaluation hooks

## Quick run

```bash
# From repo root
make server-run

cd examples/strands_agents
uv pip install -e . --upgrade

# interactive demo
uv run setup_interactive_controls.py
uv run streamlit run interactive_support_demo.py

#OR 
# steering_demo
uv run setup_email_controls.py
uv run streamlit run email_safety_demo.py

```

Full walkthrough: https://docs.agentcontrol.dev/examples/aws-strands
