# Agent Control TypeScript SDK

TypeScript SDK for [Agent Control](https://github.com/agentcontrol/agent-control).

## Installation

```bash
npm install agent-control
```

```bash
pnpm add agent-control
```

```bash
yarn add agent-control
```

Requirements:

- Node.js `>=20`

## Quick Start

Create a client instance and initialize it with server + auth config:

```ts
import { AgentControlClient } from "agent-control";

const client = new AgentControlClient();

client.init({
  agentName: "customer-support-agent",
  serverUrl: "http://localhost:8000",
  apiKey: process.env.AGENT_CONTROL_API_KEY,
});

const health = await client.system.healthCheckHealthGet();
console.log(health.status, health.version);

const agents = await client.agents.listAgentsApiV1AgentsGet({
  limit: 20,
  name: "support",
});
console.log(agents.agents.length);

const created = await client.controls.createControlApiV1ControlsPut({
  name: "deny-pii",
});
console.log(created.controlId);
```

Use the default singleton if you prefer:

```ts
import agentControl from "agent-control";

agentControl.init({
  agentName: "singleton-client",
  serverUrl: "http://localhost:8000",
  apiKey: process.env.AGENT_CONTROL_API_KEY,
});

const health = await agentControl.system.healthCheckHealthGet();
console.log(health.status);
```

## Monorepo Example

For a runnable example app inside this repository that installs `agent-control` from npm, see:

- [`examples/typescript_sdk/`](../../examples/typescript_sdk/)

## API Namespaces

`AgentControlClient` exposes generated endpoint groups directly:

- `client.agents`
- `client.controls`
- `client.evaluation`
- `client.evaluatorConfigs`
- `client.evaluators`
- `client.observability`
- `client.policies`
- `client.system`

Generated method names currently mirror OpenAPI operation IDs.
Example: `client.agents.listAgentsApiV1AgentsGet(...)`.

## Exported API

Current public exports:

- `default`: singleton `AgentControlClient`
- `AgentControlClient`
- `control`
- `ControlViolationError`
- endpoint API types: `AgentsApi`, `ControlsApi`, `EvaluationApi`, `EvaluatorConfigsApi`, `EvaluatorsApi`, `ObservabilityApi`, `PoliciesApi`, `SystemApi`
- generated request/response types via package root type exports (models + operations)
- utility types: `AgentControlInitOptions`, `StepSchema`, `ControlAction`, `EvaluationResult`, `JsonPrimitive`, `JsonValue`, `JsonObject`

## Current Status

Current implementation status:

- `AgentControlClient` makes real API calls through the generated Speakeasy client.
- Auth is sent using `X-API-Key` when `apiKey` is configured.
- `control(...)` remains a pass-through wrapper (no enforcement behavior yet).

## Development

```bash
make install
make speakeasy-install
make generate
make lint
make typecheck
make test
make build
```

Notes:

- OpenAPI source: `../../server/openapi.json`
- Generated code location: `src/generated/`
- Speakeasy CLI version is sourced from `.speakeasy/workflow.yaml` and downloaded into `.speakeasy/bin/`

Release:

- Package name: `agent-control`
- Release runbook: `RELEASING.md`
