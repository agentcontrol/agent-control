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

Use the default singleton client:

```ts
import agentControl, { control } from "agent-control";

agentControl.init({
  agentName: "customer-support-agent",
  agentId: "support-agent-v1",
  serverUrl: "http://localhost:8000",
  apiKey: process.env.AGENT_CONTROL_API_KEY,
  steps: [
    {
      name: "respond",
      schema: {
        type: "object",
        properties: {
          message: { type: "string" },
        },
      },
    },
  ],
});

const guardedRespond = control(async (message: string) => {
  return `echo:${message}`;
});

const result = await guardedRespond("hello");
console.log(result);
```

Use an explicit client instance:

```ts
import { AgentControlClient } from "agent-control";

const client = new AgentControlClient();

client.init({
  agentName: "my-agent",
  serverUrl: "http://localhost:8000",
});

console.log(client.initialized); // true
console.log(client.config?.agentName); // "my-agent"
```

## Error Handling

```ts
import { ControlViolationError } from "agent-control";

try {
  // your guarded call
} catch (error) {
  if (error instanceof ControlViolationError) {
    console.error("Blocked by control:", error.controlName);
    console.error("Reason:", error.evaluationResult.reason);
  } else {
    throw error;
  }
}
```

## Exported API

Current public exports:

- `default`: singleton `AgentControlClient`
- `AgentControlClient`
- `control`
- `ControlViolationError`
- types: `AgentControlInitOptions`, `StepSchema`, `ControlAction`, `EvaluationResult`, `JsonPrimitive`, `JsonValue`, `JsonObject`

## Current Status

This package is in scaffold phase:

- `AgentControlClient.init(...)` stores configuration.
- `control(...)` currently wraps and forwards calls (no-op enforcement path).
- The generated low-level API client is included in source but is not yet exported as public API.

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
