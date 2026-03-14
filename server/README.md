# Agent Control Server

FastAPI server that powers Agent Control. It manages agents and controls, evaluates requests at runtime, and exposes REST APIs used by the SDKs and UI.

## What it provides

- Agent registration and control association
- Control CRUD and evaluator configuration
- Runtime evaluation (`/api/v1/evaluation`) with pre/post stages
- Observability endpoints for events and stats
- API key authentication for production deployments

## Quick start (local)

From the repo root:

```bash
make sync
make server-run
```

Server runs on http://localhost:8000. The UI expects this base URL by default.

## Configuration

Server configuration is driven by environment variables (database, auth, observability, evaluators). For the full list and examples, see the docs.

Server-owned configuration now uses `AGENT_CONTROL_`-prefixed environment variables.
Examples: `AGENT_CONTROL_DB_URL`, `AGENT_CONTROL_HOST`, `AGENT_CONTROL_PORT`,
`AGENT_CONTROL_CORS_ORIGINS`, `AGENT_CONTROL_LOG_LEVEL`,
`AGENT_CONTROL_OBSERVABILITY_ENABLED`.

Full guide: https://docs.agentcontrol.dev/components/server
