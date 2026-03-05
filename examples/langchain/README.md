# LangChain SQL Agent

Protect a SQL agent from dangerous queries with server-side controls.

## Quick run

```bash
# From repo root
make server-run
export OPENAI_API_KEY="your-key-here"

cd examples/langchain
uv run pip install -e . --upgrade
uv run python setup_sql_controls.py
uv run python sql_agent_protection.py
```

Full walkthrough: [LangChain SQL Agent](https://docs.agentcontrol.dev/examples/langchain-sql)
