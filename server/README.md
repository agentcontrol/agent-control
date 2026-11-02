# Agent Control Server

FastAPI server that powers Agent Control. It manages agents and controls, evaluates requests at runtime, and exposes REST APIs used by the SDKs and UI.

## What it provides

- Agent registration and control association
- Control CRUD and evaluator configuration
- Runtime evaluation (`/api/v1/evaluation`) with pre/post stages
- Authenticated inference gateway preflight, route decision, and usage settlement
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

### Inference gateway POC API

Create a regular Agent Control with the budget evaluator, set gateway_routing
in its evaluator config, choose the route action, and bind the control to the
agent through the existing control-binding flow. Routing configuration is
stored with the control and uses the same budget evaluator store as usage
settlement. Example payloads for the distinct customer-success-agent and
claude-code controls are in
[examples/inference_gateway_poc/gateway_controls.json](../examples/inference_gateway_poc/gateway_controls.json).
The route action is accepted only with a single budget evaluator configured
with gateway_routing. It is non-blocking in ordinary ControlEngine safety
results; the gateway maps its matched evaluator metadata to a route or deny.
The Claude Code route is restricted at runtime to the Anthropic provider and
protocol. The route path selects the agent policy and attribution identity; the
runtime token binds either that agent or a log stream. A body-supplied agent
name cannot select another agent's controls.

Gateway runtime tokens may be bound to a Galileo log stream rather than the
gateway agent name. In that mode the adapter includes the stream's UUID as
`log_stream_id` on preflight, route-decision, and usage-settlement requests;
Agent Control checks that UUID against the runtime token and includes controls
bound to `(log_stream, log_stream_id)` when evaluating the controls effective
for the path agent. The `{agent_name}` route remains the policy-selection and
attribution identity. Legacy agent-bound runtime tokens remain supported when
`log_stream_id` is omitted.

`POST /api/v1/gateway/agents/{agent_name}/route-decision` combines control
preflight and tier selection. A gateway that needs a separate eligibility check
can call `/preflight` with the same request first. The route path carries the
agent identity; the optional body `agent_name` is retained only for legacy
clients and must match it. A route-decision request looks like:

```json
{
  "log_stream_id": "00000000-0000-4000-8000-000000000001",
  "task_type": "analysis",
  "task_context": {"classification": "multi-step reasoning"},
  "candidate_models": [
    {"provider": "openai", "model": "gpt-4.1-mini", "protocol": "openai"},
    {"provider": "openai", "model": "gpt-4.1", "protocol": "openai"}
  ]
}
```

For that request, the route response has this shape:

```json
{
  "allowed": true,
  "policy": "customer-success-agent-gateway-routing",
  "budget": {
    "used_tokens": 0,
    "limit_tokens": 100000,
    "utilization": 0.0,
    "threshold": 0.8,
    "threshold_reached": false,
    "over_limit": false
  },
  "reason": "Task type 'analysis' routed to the 'premium' tier.",
  "provider": "openai",
  "model": "gpt-4.1",
  "protocol": "openai",
  "task_type": "analysis",
  "decision": "route",
  "action": "route"
}
```

`budget.used_tokens` and `budget.limit_tokens` are token counts. `utilization`
and `threshold` are ratios from 0 to 1; this API does not report USD cost. A
denied decision sets `provider`, `model`, and `protocol` to null. The legacy
single-model `model` request field and optional body `agent_name` remain
accepted. The route response returns decision=route only when a bound
gateway-routing control selects a candidate. Denials return decision=deny and
null provider/model/protocol values.

After the provider responds, post the actual usage to
`POST /api/v1/gateway/agents/{agent_name}/usage-settlement`:

```json
{
  "log_stream_id": "00000000-0000-4000-8000-000000000001",
  "model": "gpt-4.1",
  "input_tokens": 40000,
  "output_tokens": 20000
}
```

Exchange the caller's request-time Galileo API key with
`POST /api/v1/auth/runtime-token-exchange` using
`{"target_type":"log_stream","target_id":"<log_stream_id>"}`. When
Agent Control uses the HTTP-upstream authorization provider, it forwards the
incoming `X-API-Key` as both `X-API-Key` and `Galileo-API-Key` so Galileo AuthZ
can authorize the stream target. The key is forwarded per request and is not
stored by Agent Control.

The settlement response uses the same budget fields and identifies the bound
control:

```json
{
  "policy": "customer-success-agent-gateway-routing",
  "budget": {
    "used_tokens": 60000,
    "limit_tokens": 100000,
    "utilization": 0.6,
    "threshold": 0.8,
    "threshold_reached": false,
    "over_limit": false
  },
  "reason": "Usage settled against the authenticated agent budget."
}
```

Budget snapshots and settlement use the budget evaluator's process-local
store. The demo records actual token usage after inference; it does not reserve
tokens across concurrent requests, so requests already in flight can exceed the
final configured budget.

Full guide: https://docs.agentcontrol.dev/components/server
