<p align="center">
  <img
    src="docs/images/AgentControl-logo-light.svg#gh-light-mode-only"
    alt="Agent Control Logo (light)"
    width="120"
  />
  <img
    src="docs/images/AgentControl-logo-dark.svg#gh-dark-mode-only"
    alt="Agent Control Logo (dark)"
    width="120"
  />
</p>

<h1 align="center">Agent Control</h1>

<p align="center">
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+" /></a>
  <a href="https://pypi.org/project/agent-control-sdk/"><img src="https://img.shields.io/pypi/v/agent-control-sdk.svg" alt="PyPI version" /></a>
  <a href="https://www.npmjs.com/package/agent-control"><img src="https://img.shields.io/npm/v/agent-control.svg" alt="npm version" /></a>
  <a href="https://github.com/agentcontrol/agent-control/actions/workflows/ci.yml"><img src="https://github.com/agentcontrol/agent-control/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://codecov.io/gh/agentcontrol/agent-control"><img src="https://codecov.io/gh/agentcontrol/agent-control/branch/main/graph/badge.svg" alt="codecov" /></a>
</p>

<p align="center">
  <a href="https://agentcontrol.dev">Agent Control Website</a> |
  <a href="https://docs.agentcontrol.dev/">Docs</a> |
  <a href="https://docs.agentcontrol.dev/core/quickstart">Quickstart</a> |
  <a href="examples/README.md">Examples</a> |
  <a href="https://join.slack.com/t/agentcontrol/shared_invite/zt-3se2g6d68-iGmNdRfGcD31cZ0vELMPxw">Slack</a>
</p>

Enforce runtime guardrails through a centralized control layer—configure once and apply across all agents. Agent Control evaluates inputs and outputs against configurable rules to block prompt injections, PII leakage, and other risks without changing your agent’s code.

![Agent Control Overview](docs/images/AgentControlDiagram.png)

- **Centralized safety** - define controls once, apply across agents, update without redeploying
- **Runtime configuration** - manage controls via API or UI, no code changes needed
- **Pluggable evaluators** - built-in (regex, list, JSON, SQL) or bring your own
- **Framework support** - works with LangChain, CrewAI, Google ADK, AWS Strands, and more

## Quick Start

Prerequisites: Docker and Python 3.12+.

Quick start flow:

```
Start server
  ↓
Install SDK
  ↓
Wrap a model or tool call with @control() and register your agent
  ↓
Create controls (UI or SDK/API)
```

### 1. Start the server

No repo clone required:

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml | docker compose -f - up -d
```

This starts PostgreSQL and Agent Control at `http://localhost:8000`, including
the UI/dashboard.

To override the exposed host ports, set `AGENT_CONTROL_SERVER_HOST_PORT` and/or
`AGENT_CONTROL_DB_HOST_PORT` before starting Compose. Example:

```bash
export AGENT_CONTROL_SERVER_HOST_PORT=18000
export AGENT_CONTROL_DB_HOST_PORT=15432
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml | docker compose -f - up -d
```

To override the bundled PostgreSQL password, set
`AGENT_CONTROL_POSTGRES_PASSWORD` before starting Compose. This value is used
for both the Postgres container and the server's database connection. Example:

```bash
export AGENT_CONTROL_POSTGRES_PASSWORD=agent_control_local
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml | docker compose -f - up -d
```

Verify it is up:

```bash
curl http://localhost:8000/health
```

If you changed `AGENT_CONTROL_SERVER_HOST_PORT`, use that port in the health check URL.

### 2. Install the SDK

Run this in your agent project directory.

Python:

```bash
uv venv
source .venv/bin/activate
uv pip install agent-control-sdk
```

TypeScript:

- See the [TypeScript SDK example](examples/typescript_sdk/README.md).

### 3. Wrap a call and register your agent

```python
# my_agent.py

import asyncio
import agent_control
from agent_control import control, ControlViolationError

# Protect any function (like LLM calls)

@control()
async def chat(message: str) -> str:
    # In production: response = await LLM.ainvoke(message)
    # For demo: simulate LLM that might leak sensitive data
    if "test" in message.lower():
        return "Your SSN is 123-45-6789"  # Will be blocked!
    return f"Echo: {message}"

# Initialize your agent

agent_control.init(
    agent_name="awesome_bot_3000",  # Unique name
    agent_description="My Chatbot",
)

async def main():
    try:
        print(await chat("test"))  # ❌ Blocked
    except ControlViolationError as e:
        print(f"❌ Blocked: {e.control_name}")
    finally:
        await agent_control.ashutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

Use `agent_control.shutdown()` or `await agent_control.ashutdown()` before process exit so short-lived scripts flush pending observability events cleanly.

Next, create a control in Step 4, then run the setup and agent scripts in
order to see blocking in action.

### 4. Add controls

This example adds the control with a small SDK setup script. You can also
create and attach controls through the UI or direct API calls.

Minimal SDK example (assumes the server is running at `http://localhost:8000`
and uses the same `agent_name` as Step 3):

```python
# setup.py - Run once to configure agent controls

import asyncio
from datetime import datetime, UTC
from agent_control import AgentControlClient, controls, agents
from agent_control_models import Agent

async def setup():
    async with AgentControlClient() as client:  # Defaults to localhost:8000
        # 1. Register agent first
        agent = Agent(
            agent_name="awesome_bot_3000",
            agent_description="My Chatbot",
            agent_created_at=datetime.now(UTC).isoformat(),
        )
        await agents.register_agent(client, agent, steps=[])

        # 2. Create control (blocks SSN patterns in output)
        control = await controls.create_control(
            client,
            name="block-ssn",
            data={
                "enabled": True,
                "execution": "server",
                "scope": {"stages": ["post"]},
                "condition": {
                    "selector": {"path": "output"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
                    },
                },
                "action": {"decision": "deny"},
            },
        )

        # 3. Associate control directly with agent
        await agents.add_agent_control(
            client,
            agent_name=agent.agent_name,
            control_id=control["control_id"],
        )

        print("✅ Setup complete!")
        print(f"   Control ID: {control['control_id']}")

asyncio.run(setup())
```

Controls now store leaf `selector` and `evaluator` definitions under `condition`, which also enables composite `and`, `or`, and `not` trees.

**Tip**: If you prefer a visual flow, use the UI instead - see the [UI Quickstart](https://docs.agentcontrol.dev/core/ui-quickstart).

Run both scripts in order:

```bash
uv run setup.py
uv run my_agent.py
```

Expected output:

```text
Blocked: block-ssn-demo
```

## Examples:

Explore working examples for popular frameworks.

- [Customer Support Agent](examples/customer_support_agent/) - PII protection, prompt injection defense, and tool controls
- [Steer Action Demo](examples/steer_action_demo/) - observe, deny, and steer decisions in one workflow
- [LangChain](examples/langchain/) - protect a SQL agent from dangerous queries
- [CrewAI](examples/crewai/) - combine Agent Control with CrewAI guardrails
- [AWS Strands](examples/strands_agents/) - protect Strands workflows and tool calls
- [Google ADK Decorator](examples/google_adk_decorator/) - add controls with `@control()`

## How It Works

![Agent Control Architecture](docs/images/Architecture.png)

Agent Control evaluates agent inputs and outputs against controls you configure at runtime. That keeps guardrail logic out of prompt code and tool code, while still letting teams update protections centrally.

Read more about [Controls](https://docs.agentcontrol.dev/concepts/controls) and Learn how controls, selectors, and evaluators work

## Performance

| Endpoint         | Scenario                      | RPS     | p50      | p99      |
| ---------------- | ----------------------------- | ------- | -------- | -------- |
| Agent init       | Agent with 3 tool steps       | 509     | 19 ms    | 54 ms    |
| Evaluation       | 1 control, 500-char content   | 437     | 36 ms    | 61 ms    |
| Evaluation       | 10 controls, 500-char content | 349     | 35 ms    | 66 ms    |
| Evaluation       | 50 controls, 500-char content | 199     | 63 ms    | 91 ms    |
| Controls refresh | 5-50 controls per agent       | 273-392 | 20-27 ms | 27-61 ms |

- Agent init handles create and update as an upsert.
- Local laptop benchmarks are directional, not production sizing guidance.

_Benchmarked on Apple M5 (16 GB RAM), Docker Compose (`postgres:16` + `agent-control`)._

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines, development workflow, and quality checks.

## License

Apache 2.0. See [LICENSE](LICENSE) for details.
