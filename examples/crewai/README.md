# CrewAI Example

Combine Agent Control security controls with CrewAI guardrails for customer support workflows.

## What this example shows

- Pre/post controls for access and PII protection
- CrewAI guardrails for quality retries
- Multi-layer control enforcement

## Quick run

```bash
# From repo root
make server-run
export OPENAI_API_KEY="your-key-here"

# In a separate shell
cd examples/crewai
uv pip install -e . --upgrade
uv run python setup_content_controls.py
uv run python content_agent_protection.py
```

Full walkthrough: https://docs.agentcontrol.dev/examples/crewai
