# LangChain SQL Agent

Protect a SQL agent from dangerous queries with server-side controls.

## What this example shows

- SQL control configuration
- Safe vs. unsafe query handling
- LangChain integration

## Quick run

```bash
# From repo root
export OPENAI_API_KEY="your-key-here"
make server-run


# In separate shell
cd examples/langchain
uv pip install -e . --upgrade
uv run python setup_sql_controls.py
uv run python sql_agent_protection.py
```

Full walkthrough: https://docs.agentcontrol.dev/examples/langchain-sql
