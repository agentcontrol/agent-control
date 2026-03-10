# Agent Control

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/agent-control-sdk.svg)](https://pypi.org/project/agent-control-sdk/)
[![npm version](https://img.shields.io/npm/v/agent-control.svg)](https://www.npmjs.com/package/agent-control)
[![CI](https://github.com/agentcontrol/agent-control/actions/workflows/ci.yml/badge.svg)](https://github.com/agentcontrol/agent-control/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/agentcontrol/agent-control/branch/main/graph/badge.svg)](https://codecov.io/gh/agentcontrol/agent-control)

> **💡 Pro Tip:** Checkout [docs](https://docs.agentcontrol.dev/) for complete reference

> **👋 Say hello to us:** Checkout our [Slack](https://join.slack.com/t/agentcontrol/shared_invite/zt-3s2pbclup-T4EJ5sA7SOxR6jTeETZljA).  Pop in to ask for help, suggest features, or just to say hello!

**Runtime guardrails for AI agents — configurable, extensible, and production-ready.**

AI agents interact with users, tools, and external systems in unpredictable ways. **Agent Control** provides an extensible, control-based runtime layer that evaluates inputs and outputs against configurable rules — blocking prompt injections, PII leakage, and other risks without modifying your agent's code.

![Agent Control Architecture](docs/images/Architecture.png)


## Why Do You Need It?
Traditional guardrails embedded inside your agent code have critical limitations:

- **Scattered Logic:** Control code is buried across your agent codebase, making it hard to audit or update
- **Deployment Overhead:** Changing protection rules requires code changes and redeployment
- **Limited Adaptability:** Hardcoded checks can't adapt to new attack patterns or production data variations

**Agent Control gives you runtime control over what your agents can and cannot do:**
- **For developers:** Centralize safety logic and adapt to emerging threats instantly without redeployment
- **For non-technical teams:** Intuitive UI to configure and monitor agent safety without touching code
- **For organizations:** Reusable controls across agents with comprehensive audit trails

## Key Features

- **Safety Without Code Changes** — Add guardrails with a `@control()` decorator
- **Runtime Configuration** — Update controls instantly via API or UI without having to re-deploy your agentic applications
- **Centralized Controls** — Define controls once, apply to multiple agents
- **Web Dashboard** — Visual interface for managing agents, controls, and viewing analytics
- **Pluggable Evaluators** — Built-in (regex, list matching, Luna-2 AI) or custom evaluators
- **Fail-Safe Defaults** — Deny controls fail closed on error with configurable error handling
- **API Key Authentication** — Secure your control server in production

## Performance

| Endpoint | Scenario | RPS | p50 | p99 |
|----------|----------|-----|-----|-----|
| Agent init | Agent with 3 tool steps | 509 | 19 ms | 54 ms |
| Evaluation | 1 control, 500-char content | 437 | 36 ms | 61 ms |
| Evaluation | 10 controls, 500-char content | 349 | 35 ms | 66 ms |
| Evaluation | 50 controls, 500-char content | 199 | 63 ms | 91 ms |
| Controls refresh | 5-50 controls per agent | 273-392 | 20-27 ms | 27-61 ms |

- Agent init handles both create and update identically (upsert).
- All four built-in evaluators (regex, list, JSON, SQL) perform within 40-46 ms p50 at 1 control.
- Moving from 1 to 50 controls increased evaluation p50 by about 27 ms.
- Local laptop benchmarks are directional and intended for developer reference. They are not production sizing guidance.

_Benchmarked on Apple M5 (16 GB RAM), Docker Compose (`postgres:16` + `agent-control`). 2 minutes per scenario, 5 concurrent users for latency (p50, p99), 10-20 for throughput (RPS). RPS = completed requests per second. All scenarios completed with 0% errors._

### Examples

Explore real-world integrations with popular agent frameworks, or jump to [Quick Start](#quick-start) for hands-on setup. 

- **[Examples Overview](examples/README.md)** — Working code examples and integration patterns
- **[TypeScript SDK (npm consumer)](examples/typescript_sdk/)** — Monorepo example that installs `agent-control` from npm
- **[Customer Support Agent](examples/customer_support_agent/)** — Full example with multiple tools
- **[LangChain SQL Agent](examples/langchain/)** — SQL injection protection with LangChain
- **[Galileo Luna-2 Integration](examples/galileo/)** — AI-powered toxicity detection
- **[CrewAI SDK Integration](examples/crewai/)** — Working example on integrating with third party Agent SDKs and using Agent Control along side their guardrails
- **[DeepEval Integration](examples/deepeval/)** — Working Example on How to create custom evaluators to use with your controls

## Quick start

### Installation

**Prerequisites**: 
* Python 3.12+ 
* Docker 

#### SDK only 
Install our SDK in your project - `pip install agent-control-sdk` 
> **📝 Note:** Depending on your setup the command maybe different such as `uv add agent-control-sdk` if you're using uv.

Run the Agent Control server and Postgres database via docker compose:
```commandline
curl "https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml" | docker compose -f - up -d
```

Server will be running at `http://localhost:8000`

#### Local development

**Prerequisites:** 
* uv: Fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
* Node.js 18+: For the web dashboard (optional)

```bash
# Clone the repo
git clone https://github.com/agentcontrol/agent-control.git
cd agent-control

# Install dependencies
make sync

# Start the Agent Control server.  This will also boot Postgres and run alembic migrations
make server-run

# Start the UI (in a separate shell)
make ui-install
make ui-dev
```
* Server will run on `http://localhost:8000`
* UI will run on `http://localhost:4000`

### Onboarding your agent

#### Register your agent with server

Agent must be registered with the server.  You should also add `@control` decorator around tools and llm call functions.

Here is a contrived example.  Reference our [examples](/examples) for real world examples for specific frameworks.
```python
# my_agent.py
import asyncio
import agent_control
from agent_control import control, ControlViolationError

# Protect any function (like LLM calls)
@control()
async def chat(message: str) -> str:
    # In production: response = await llm.ainvoke(message)
    # For demo: simulate LLM that might leak sensitive data
    if "test" in message.lower():
        return "Your SSN is 123-45-6789"  # Will be blocked!
    return f"Echo: {message}"

# Initialize your agent
agent_control.init(
    agent_name="awesome_bot_3000", # This should be a unique name 
    agent_description="My Chatbot",
)

# Test it
async def main():
    try:
        print(await chat("test"))  # ❌ Blocked
    except ControlViolationError as e:
        print(f"❌ Blocked: {e.control_name}")

asyncio.run(main())
```

#### Add some controls

Easiest way to add controls is to use the UI.  

You can also use SDK or directly call api:

> When authentication is enabled, this setup script needs an admin API key because it
> creates a control and attaches it to an agent. `agents.register_agent()` itself accepts
> a regular or admin key, but `controls.create_control()` and
> `agents.add_agent_control()` are control-plane mutations and require a key listed in
> `AGENT_CONTROL_ADMIN_API_KEYS`.
>
> If you started the full local stack with the repo-root `docker-compose.yml`, it enables
> auth with these development defaults:
> - Regular API key: `420c6b90714b45beaa992c3f05cf2baf`
> - Admin API key: `29af8554a1fe4311977b7ce360b20cc3`
> - UI default key (`NEXT_PUBLIC_AGENT_CONTROL_API_KEY`): `29af8554a1fe4311977b7ce360b20cc3`
>
> Replace these defaults before any shared or production deployment.

```python
# setup.py - Run once to configure everything
import asyncio
import os
from datetime import datetime, UTC
from agent_control import AgentControlClient, controls, agents
from agent_control_models import Agent

async def setup():
    async with AgentControlClient(
        api_key=os.getenv("AGENT_CONTROL_API_KEY")
    ) as client:  # Defaults to localhost:8000
        # 1. Register agent first
        agent = Agent(
            # Your agent's UUID
            agent_name="550e8400-e29b-41d4-a716-446655440000",
            agent_description="My Chatbot",
            agent_created_at=datetime.now(UTC).isoformat()
        )
        await agents.register_agent(client, agent, steps=[])

        # 2. Create control (blocks SSN patterns)
        control = await controls.create_control(
            client,
            name="block-ssn",
            data={
                "enabled": True,
                "execution": "server",
                "scope": {"stages": ["post"]},
                "selector": {"path": "output"},
                "evaluator": {
                    "name": "regex", # Inbuilt regex evaluator. See agent-control/evaluators to see all available OOTB evaluators
                    "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}
                },
                "action": {"decision": "deny"}
            }
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
#### What's Happening Under the Hood?

1. Your app calls `chat("test")`
2. Function executes and returns `"Your SSN is 123-45-6789"`
3. `@control()` decorator sends output to Agent Control server
4. Server checks the output against all controls
5. `block-ssn` control finds SSN pattern → matches!
6. Server returns `is_safe=False` with the matched control
7. SDK raises `ControlViolationError` and blocks the response

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_CONTROL_URL` | `http://localhost:8000` | Server URL for SDK |
| `AGENT_CONTROL_API_KEY` | — | API key for authentication (if enabled) |
| `DB_URL` | `postgresql+psycopg://agent_control:agent_control@localhost:5432/agent_control` | Database connection string (SQLite: `sqlite+aiosqlite:///./agent_control.db`) |
| `GALILEO_API_KEY` | — | Required for Luna-2 AI evaluator |

### Server Configuration

The server supports additional environment variables:

- `AGENT_CONTROL_API_KEY_ENABLED` - Enable API key authentication (default: `false`)
- `AGENT_CONTROL_API_KEYS` - Valid API keys for runtime/read access when auth is enabled
- `AGENT_CONTROL_ADMIN_API_KEYS` - Admin API keys required for control-plane mutations
- `LOG_LEVEL` - Logging level (default: `INFO`)

See [server/README.md](server/README.md) for complete server configuration.

---

## Agent Control Components

Agent Control is built as a monorepo with these components:

```
┌──────────────────────────────────────────────────────────────────┐
│                         Your Application                         │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                     @control() decorator                   │  │
│  │                            │                               │  │
│  │                            ▼                               │  │
│  │  ┌──────────┐    ┌─────────────────┐    ┌──────────────┐   │  │
│  │  │  Input   │───▶│  Agent Control  │───▶│    Output    │   │  │
│  │  │          │    │     Engine      │    │              │   │  │
│  │  └──────────┘    └─────────────────┘    └──────────────┘   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Agent Control Server                        │
│                                                                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │  Controls  │  │Control Link│  │ Evaluators │  │   Agents   │  │
│  │    API     │  │    API     │  │  Registry  │  │    API     │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Evaluator Ecosystem                        │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │   Regex    │  │    List    │  │   Luna-2   │  │   Custom   │  │
│  │ Evaluator  │  │ Evaluator  │  │ Evaluator  │  │ Evaluators │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

| Package | Description |
|:--------|:------------|
| `agent-control-sdk` | Python SDK with `@control()` decorator |
| `agent-control` (npm) | TypeScript SDK (generated from OpenAPI) |
| `agent-control-server` | FastAPI server with Control Management API |
| `agent-control-engine` | Core evaluation logic and evaluator system |
| `agent-control-models` | Shared Pydantic v2 models |
| `agent-control-evaluators` | Built-in evaluators |
| `ui` | Next.js web dashboard |

---

## Development

### Directory Structure

```
agent-control/
├── sdks/python/     # Python SDK (agent-control)
├── sdks/typescript/ # TypeScript SDK (generated)
├── server/          # FastAPI server (agent-control-server)
├── engine/          # Evaluation engine (agent-control-engine)
├── models/          # Shared models (agent-control-models)
├── evaluators/      # Evaluator implementations (agent-control-evaluators)
├── ui/              # Next.js web dashboard
└── examples/        # Usage examples
```

### Makefile Commands

The project uses a Makefile for common tasks:

| Command | Description |
|:--------|:------------|
| `make sync` | Install dependencies for all workspace packages |
| `make test` | Run tests across all packages |
| `make lint` | Run ruff linting |
| `make lint-fix` | Run ruff with auto-fix |
| `make typecheck` | Run mypy type checking |
| `make check` | Run all quality checks (test + lint + typecheck) |
| `make server-run` | Start the server |
| `make server-<target>` | Forward commands to server (e.g., `make server-alembic-upgrade`) |
| `make sdk-<target>` | Forward commands to SDK (e.g., `make sdk-test`) |
| `make engine-<target>` | Forward commands to engine (e.g., `make engine-test`) |

For detailed development workflows, see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Documentation

### Core Documentation

- **[Reference Guide](docs/REFERENCE.md)** — Complete reference for concepts, evaluators, SDK, and API
- **[Contributing Guide](CONTRIBUTING.md)** — Development setup and contribution guidelines
- **[Testing Guide](docs/testing.md)** — Testing conventions and best practices

### Component Documentation

- **[Python SDK](sdks/python/README.md)** — SDK installation, usage, and API reference
- **[Server](server/README.md)** — Server setup, configuration, and deployment
- **[UI Dashboard](ui/README.md)** — Web dashboard setup and usage
- **[Evaluators](evaluators/README.md)** — Available evaluators and custom evaluator development

## Contributing

We welcome contributions! To get started:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run quality checks (`make check`)
5. Commit using conventional commits (`feat:`, `fix:`, `docs:`, etc.)
6. Submit a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines, code conventions, and development workflow.

---

## License

Apache 2.0 — See [LICENSE](LICENSE) for details.
