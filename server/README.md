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

To use non-default local ports with `make server-run`, export
`AGENT_CONTROL_PORT` for the server listen port. If you also want the local
Postgres container exposed on a different host port, set
`AGENT_CONTROL_DB_HOST_PORT` and point the server at the same value with
`AGENT_CONTROL_DB_PORT`.

## Database migrations

The server package includes the `agent-control-migrate` command for bundled
Alembic migrations.

In production, migrations are serialized with a Postgres advisory lock. Alembic
runs each migration revision in its own transaction, so if an upgrade across
multiple revisions fails, earlier revisions may already be committed. Check the
current revision before retrying:

```bash
agent-control-migrate current
agent-control-migrate upgrade head
```

## PostgreSQL driver runtime

`agent-control-server` depends on plain `psycopg`. The published Docker image
installs Debian `libpq5` and sets `PSYCOPG_IMPL=python` so the server uses
psycopg's Python implementation with the OS libpq library.

For wheel-based deployments outside Docker, either install the OS libpq runtime
package for your platform, or install `agent-control-server[binary]` if you want
psycopg's bundled binary package.

## Configuration

Server configuration is driven by environment variables (database, auth, observability, evaluators). For the full list and examples, see the docs.

Full guide: https://docs.agentcontrol.dev/components/server

## Authorization operation compatibility

Custom and HTTP upstream authorizers must recognize every operation emitted by the server. The
agent mutation routes use these dedicated wire operations:

- `agents.recover` for `force_replace=true` on an existing agent
- `agent_control_associations.write` for adding or removing a direct agent-control association
- `agent_policy_associations.write` for adding, setting, removing, or clearing agent-policy
  associations

Normal registration overwrite/strict mutations and `PATCH /agents/{agent_name}` continue to use
`agents.update`. The built-in header provider requires admin credentials for all four mutation
operations. When upgrading a deployment with an HTTP authorization upstream, add support for the
new operation values upstream before deploying this server version; unrecognized operations fail
closed and will interrupt the affected requests.
