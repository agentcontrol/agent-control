# Anthropic Chat Demo — UI-driven policy

Six prompts → Claude Sonnet, wrapped with `@control`. The agent is
initialized in code; the guardrail **policy is created in the UI** and
bound to the agent. Re-run the script to see your policy take effect.

## Prereqs

- Agent Control server + UI running (e.g. `docker compose up -d` from repo root)
- `ANTHROPIC_API_KEY`

## Run

```bash
cd examples/anthropic_chat_demo
cp .env.example .env   # then edit .env and set ANTHROPIC_API_KEY
uv run python demo.py
```

The first run registers an agent named **`anthropic-chat-demo`** with the
server.

## Create a policy in the UI

1. Open http://localhost:4000
2. Find the `anthropic-chat-demo` agent
3. Create a control / policy (e.g. block PII in inputs or outputs) and bind it
4. Re-run `uv run python demo.py` — prompts that violate the policy are
   blocked at the `@control` boundary; clean ones still reach Claude

The fourth prompt deliberately contains a fake SSN to exercise a PII rule
once you've configured one.
