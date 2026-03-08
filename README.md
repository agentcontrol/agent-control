# Agent Control

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/agent-control-sdk.svg)](https://pypi.org/project/agent-control-sdk/)
[![npm version](https://img.shields.io/npm/v/agent-control.svg)](https://www.npmjs.com/package/agent-control)
[![CI](https://github.com/agentcontrol/agent-control/actions/workflows/ci.yml/badge.svg)](https://github.com/agentcontrol/agent-control/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/agentcontrol/agent-control/branch/main/graph/badge.svg)](https://codecov.io/gh/agentcontrol/agent-control)

> **Pro Tip:** See the full docs at https://docs.agentcontrol.dev/

**Runtime guardrails for AI agents — configurable, extensible, and production-ready.**

AI agents interact with users, tools, and external systems in unpredictable ways. **Agent Control** provides an extensible, control-based runtime layer that evaluates inputs and outputs against configurable rules — blocking prompt injections, PII leakage, and other risks without modifying your agent's code.

![Agent Control Architecture](docs/images/Architecture.png)

## Why Do You Need It

Traditional guardrails embedded inside your agent code have critical limitations:

- **Scattered Logic:** Control code is buried across your agent codebase, making it hard to audit or update
- **Deployment Overhead:** Changing protection rules requires code changes and redeployment
- **Limited Adaptability:** Hardcoded checks can’t adapt to new attack patterns or production data variations

**Agent Control gives you runtime control over what your agents can and cannot do:**

- **For developers:** Centralize safety logic and adapt to emerging threats instantly without redeployment
- **For non-technical teams:** Intuitive UI to configure and monitor agent safety without touching code
- **For organizations:** Reusable controls across agents with comprehensive audit trails

## Key Features

- **Safety Without Code Changes** — Add guardrails with a `@control()` decorator
- **Runtime Configuration** — Update controls instantly via API or UI without redeploying your agentic applications
- **Centralized Controls** — Define controls once, apply to multiple agents
- **Web Dashboard** — Visual interface for managing agents, controls, and viewing analytics
- **Pluggable Evaluators** — Built-in (regex, list matching, Luna-2 AI) or custom evaluators
- **Fail-Safe Defaults** — Deny controls fail closed on error with configurable error handling
- **API Key Authentication** — Secure your control server in production

## Examples

Explore real-world integrations with popular agent frameworks, or jump to [Quick Start](#quick-start).

- **[Examples Overview](examples/README.md)** — Complete catalog of examples and patterns

### Core demos
- **[TypeScript SDK](examples/typescript_sdk/)** — Consumer-style TypeScript example using the published npm package
- **[Customer Support Agent](examples/customer_support_agent/)** — Enterprise scenario with PII protection, prompt-injection defense, and multiple tools
- **[Steer Action Demo](examples/steer_action_demo/)** — Banking transfer agent showcasing allow, deny, warn, and steer actions

### Evaluator integrations
- **[DeepEval Integration](examples/deepeval/)** — Build a custom evaluator using DeepEval GEval metrics
- **[Galileo Luna-2 Integration](examples/galileo/)** — Toxicity detection and content moderation with Galileo Protect

### Framework integrations
- **[LangChain](examples/langchain/)** — Protect a SQL agent from dangerous queries with server-side controls
- **[CrewAI](examples/crewai/)** — Combine Agent Control security controls with CrewAI guardrails for customer support
- **[AWS Strands](examples/strands_agents/)** — Guardrails for AWS Strands agent workflows and tool calls

## Quick start

Prerequisites:

- Python 3.12+
- Docker

### Option A — SDK only

Install the SDK in your project:

```bash
pip install agent-control-sdk
```

Run the Agent Control server, PostgreSQL database and UI via Docker Compose:

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml | docker compose -f - up -d
```

Server will run at `http://localhost:8000` and UI at `http://localhost:4000`.

### Option B — Local development

**Prerequisites:**

- **uv** — Fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Node.js 18+** — For the web dashboard (optional)

```bash
# Clone the repo
git clone https://github.com/agentcontrol/agent-control.git
cd agent-control

# Install all workspace dependencies
make sync

# Start the Agent Control server (boots Postgres + runs migrations)
make server-run

# Start the UI (in a separate shell)
make ui-install
make ui-dev
```

Server runs at `http://localhost:8000` and UI at `http://localhost:4000`.

Install the SDK in your project:
```bash
pip install agent-control-sdk
```

## Minimal agent integration

### Register your agent with server
Agent must be registered with the server. You should also add `@control` decorator around tools and llm call functions.

Here is a contrived example. Reference our [examples](examples/) for real world examples for specific frameworks.

```python
import asyncio
import agent_control
from agent_control import control, ControlViolationError

@control()
async def chat(message: str) -> str:
    if "test" in message.lower():
        return "Your SSN is 123-45-6789"
    return f"Echo: {message}"

agent_control.init(
    agent_name="awesome_bot_3000",
    agent_description="My Chatbot",
)

async def main():
    try:
        print(await chat("test"))
    except ControlViolationError as e:
        print(f"Blocked: {e.control_name}")

asyncio.run(main())
```

### Add some controls

**NOTE:** Easiest way to add controls is to use the UI. You can also use SDK or directly call api. 

Run following script to create controls:

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
            # Your agent's name
            agent_name="awesome_bot_3000",
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
                    "name": "regex", # Inbuilt regex evaluator. See evaluators/builtin to see all available OOTB evaluators
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

Now, when you run your agent again, you will see `Blocked: block-ssn`. 

### What's Happening Under the Hood?
1. Your app calls chat("test")
2. Function executes and returns "Your SSN is 123-45-6789"
3. `@control()` decorator sends output to Agent Control server
4. Server checks the output against all controls
5. block-ssn control finds SSN pattern → matches!
6. Server returns is_safe=False with the matched control
7. SDK raises ControlViolationError and blocks the response

For full setup, see https://docs.agentcontrol.dev/quickstart

## Documentation

### Core Documentation

- **Overview:** https://docs.agentcontrol.dev/overview
- **Quickstart:** https://docs.agentcontrol.dev/quickstart
- **Reference:** https://docs.agentcontrol.dev/reference
- **Testing:** https://docs.agentcontrol.dev/testing
- **Python SDK:** https://docs.agentcontrol.dev/sdk/python-sdk
- **TypeScript SDK:** https://docs.agentcontrol.dev/sdk/typescript-sdk

### Component Documentation
- **Server:** https://docs.agentcontrol.dev/server
- **Engine:** https://docs.agentcontrol.dev/engine
- **Models:** https://docs.agentcontrol.dev/models
- **Evaluators:** https://docs.agentcontrol.dev/evaluators
- **UI Quickstart:** https://docs.agentcontrol.dev/ui-quickstart

## Contributing

We welcome contributions! To get started:

1. Fork the repository
2. Create a feature branch (git checkout -b feature/your-feature)
3. Make your changes
4. Run quality checks (make check)
5. Commit using conventional commits (feat:, fix:, docs:, etc.)
6. Submit a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines, code conventions, and development workflow.

## License

Apache 2.0 — See [LICENSE](LICENSE) for details.
