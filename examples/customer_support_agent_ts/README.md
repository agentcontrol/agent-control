# Customer Support Agent — TypeScript Example

TypeScript port of the [Python customer support agent](../customer_support_agent/) demonstrating the `agent-control` SDK's `control()` higher-order function pattern.

## What it shows

- **`control(name, fn, opts?)`** — wrapping async functions with pre/post evaluation (LLM calls + tool calls)
- **`ControlViolationError`** handling — graceful fallbacks when a control denies
- **Pre and post controls** — block PII in input, block sensitive data in LLM output, prompt-injection and tool-scoped rules

## Prerequisites

1. Node.js 20+ and pnpm
2. Agent Control server running:
   ```bash
   make server-run          # from repo root
   ```

## Quick start

```bash
cd examples/customer_support_agent_ts
pnpm install

# 1. Create agent, controls, and policy on the server (one-time)
pnpm run setup

# 2. Run the interactive demo
pnpm start

# Or run automated test suite
pnpm start -- --automated
```

If your server uses auth:

```bash
export AGENT_CONTROL_API_KEY=your-key
pnpm run setup
pnpm start
```

## Project structure

```
customer_support_agent_ts/
├── src/
│   ├── agent.ts           # SDK init, control() wrappers, agent class
│   ├── main.ts            # Interactive demo / automated test runner
│   ├── mock-services.ts   # Simulated LLM, DB, KB, ticket system
│   └── setup-controls.ts  # Creates controls + policy via SDK
├── package.json
├── tsconfig.json
└── README.md
```

## SDK patterns demonstrated

### 1. Initialization

```typescript
import agentControl from "agent-control";

agentControl.init({
  agentName: "customer-support-agent-ts",
  serverUrl: "http://localhost:8000",
});
```

### 2. Protecting functions with `control()`

```typescript
import { control } from "agent-control";

// LLM call
const respondToCustomer = control("respond_to_customer", async (message: string) => {
  return await llm.generate(message);
});

// Tool call
const lookupCustomer = control("lookup_customer", async (query: string) => {
  return db.lookup(query);
}, { type: "tool" });
```

### 3. Handling violations

```typescript
import { ControlViolationError } from "agent-control";

try {
  const response = await respondToCustomer(userMessage);
} catch (err) {
  if (err instanceof ControlViolationError) {
    console.log(`Blocked by: ${err.controlName}`);
    return "I can't help with that request.";
  }
  throw err;
}
```

## Interactive commands

| Command | Description |
|---------|-------------|
| `/test-safe` | Run safe message tests |
| `/test-pii` | Test PII detection (pre: block SSN/card in input) |
| `/test-post` | Test post controls (block credit card in LLM output) |
| `/test-injection` | Test prompt injection controls |
| `/test-tools` | Test tool controls (lookup, search, ticket) |
| `/test-all` | Run all test suites |
| `/lookup <query>` | Look up customer (e.g. `/lookup C001`) |
| `/search <query>` | Search knowledge base |
| `/ticket [priority]` | Create a test ticket |
| `/help` | Show commands |
| `/quit` | Exit |

Or type any message to chat with the agent.
