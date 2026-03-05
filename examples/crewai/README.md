# CrewAI Example

Combine Agent Control security controls with CrewAI guardrails for customer support.

## Quick run

```bash
# From repo root
make server-run
export OPENAI_API_KEY="your-key-here"

cd examples/crewai
uv pip install -e . --upgrade
uv run python setup_content_controls.py
uv run python content_agent_protection.py
```

Full walkthrough: [CrewAI Example](https://docs.agentcontrol.dev/examples/crewai)
