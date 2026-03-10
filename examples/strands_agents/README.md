# AWS Strands Example

Automatic safety controls for AWS Strands agents using plugins - no decorators needed.

## What this example shows

- Integration points for Strands agents
- Control configuration patterns
- Runtime evaluation hooks

## Quick run

```bash
# From repo root
make server-run

# In separate shell
cd examples/strands_agents
uv pip install -e . --upgrade

# interactive demo
uv run interactive_demo/setup_interactive_controls.py
uv run streamlit run interactive_demo/interactive_support_demo.py

# OR
# steering demo
uv run steering_demo/setup_email_controls.py
uv run streamlit run steering_demo/email_safety_demo.py

```

Full walkthrough: https://docs.agentcontrol.dev/examples/aws-strands

Read more about Agent Control integration with Strands at [Integration Docs](https://docs.agentcontrol.dev/integrations/strands)

See integration source code in [sdks/python/src/agent_control/integrations/strands](../../sdks/python/src/agent_control/integrations/strands)
