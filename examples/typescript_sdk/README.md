# TypeScript SDK Example (npm Consumer)

This example lives in the monorepo, but it intentionally uses the published npm package:

```bash
npm install agent-control
```

It demonstrates how an external TypeScript app can consume Agent Control without using local workspace linking.

Use an `agent-control` npm version compatible with your server version (this example currently pins `0.2.0`).

## Prerequisites

1. Node.js 20+
2. Agent Control server running (from repo root):
   ```bash
   make server-run
   ```
3. Optional API key (if server auth is enabled):
   ```bash
   export AGENT_CONTROL_API_KEY=your-api-key
   ```

## Run

```bash
cd examples/typescript_sdk
npm install
AGENT_CONTROL_URL=http://localhost:8000 npm run start
```

If your server requires auth:

```bash
AGENT_CONTROL_URL=http://localhost:8000 AGENT_CONTROL_API_KEY=your-api-key npm run start
```

## What It Does

The script in `src/quickstart.ts` performs:

1. SDK init with server URL and optional API key
2. health check request
3. list controls request
4. create control request
5. set/get control data requests (regex evaluator example)
6. cleanup delete of the created control

## Validate Types

```bash
npm run typecheck
```
