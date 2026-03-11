<p align="center">
  <img
    src="docs/images/AgentControl-logo-dark.svg#gh-light-mode-only"
    alt="Agent Control Logo (light)"
    width="120"
  />
  <img
    src="docs/images/AgentControl-logo-light.svg#gh-dark-mode-only"
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

> **Pro Tip:** See the full docs at [Agent Control Docs](https://docs.agentcontrol.dev/)

> **👋 Say hello to us:** Checkout our [Slack](https://join.slack.com/t/agentcontrol/shared_invite/zt-3s2pbclup-T4EJ5sA7SOxR6jTeETZljA). Pop in to ask for help, suggest features, or just to say hello!

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

---

## Examples

Explore real-world integrations with popular agent frameworks, or jump to [Quick Start](#quick-start).

- **[Examples Overview](examples/README.md)** — Complete catalog of examples and patterns
- **[TypeScript SDK](examples/typescript_sdk/)** — Consumer-style TypeScript example using the published npm package

### Core demos

- **[Customer Support Agent](examples/customer_support_agent/)** — Enterprise scenario with PII protection, prompt-injection defense, and multiple tools
- **[Steer Action Demo](examples/steer_action_demo/)** — Banking transfer agent showcasing allow, deny, warn, and steer actions

### Evaluator integrations

- **[DeepEval Integration](examples/deepeval/)** — Build a custom evaluator using DeepEval GEval metrics
- **[Galileo Luna-2 Integration](examples/galileo/)** — Toxicity detection and content moderation with Galileo Protect

### Framework integrations

- **[LangChain](examples/langchain/)** — Protect a SQL agent from dangerous queries with server-side controls
- **[CrewAI](examples/crewai/)** — Combine Agent Control security controls with CrewAI guardrails for customer support
- **[AWS Strands](examples/strands_agents/)** — Guardrails for AWS Strands agent workflows and tool calls
- **[Google ADK Callbacks](examples/google_adk_callbacks/)** — Model and tool protection using ADK's native callback hooks
- **[Google ADK Decorator](examples/google_adk_decorator/)** — Tool-level protection using Agent Control's @control() decorator

---

## Quick start

Protect your AI agent in 4 simple steps.

### Prerequisites

- Python 3.12+
- Docker

---

### ⚡ Quick Start for Developers

**Quick setup (no repo cloning required)** — Copy this into your terminal or paste it directly into your coding agent to start the Agent Control server, UI.

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml | docker compose -f - up -d
```

Then, install the SDK in a virtual environment:

```bash
uv venv
source .venv/bin/activate
uv pip install agent-control-sdk
```

**What this does:**

- ✅ Starts Agent Control server at `http://localhost:8000`
- ✅ Starts UI dashboard at `http://localhost:8000`
- ✅ Installs Python SDK (`agent-control-sdk`)

**Next:** Jump to [Step 3: Register your agent](#step-3-register-your-agent)

---

**Alternatively**, for local development with the Agent Control repository, clone the repo and follow all steps below.

### Step 1: Start the Agent Control server

Startup Agent Control server manually for local development.

#### Local development (cloning the repo)

Prerequisites:

- uv — Fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 18+ — For the web dashboard (optional)

```bash
# Clone the repository

git clone https://github.com/agentcontrol/agent-control.git
cd agent-control

# Install dependencies

make sync

# Start the Agent Control server (boots Postgres + runs migrations)

make server-run

# Start the UI (in a separate shell)

make ui-install
make ui-dev
```

- Server runs at `http://localhost:8000`
- UI runs at `http://localhost:4000`

Verify the server by opening `http://localhost:8000/health` — you should see `{"status": "healthy", "version": "..."}`.

### Step 2: Install the SDK

In your agent application project:

```bash
pip install agent-control-sdk
```

### Step 3: Register your agent

Agent must be registered with the server. You should also add the `@control` decorator around tools and LLM call functions.

Here is a contrived example. Reference our [Examples](examples/) for real-world examples for specific frameworks.

```python
# my_agent.py

import asyncio
import agent_control
from agent_control import control, ControlViolationError

@control()
async def chat(message: str) -> str:
    # In production: response = await LLM.ainvoke(message)
    # For demo: simulate LLM that might leak sensitive data
    if "test" in message.lower():
        return "Your SSN is 123-45-6789"  # Will be blocked!
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

### Step 4: Add controls

The easiest way to add controls is through the UI — see the [UI Quickstart](https://docs.agentcontrol.dev/core/ui-quickstart) for a step-by-step guide. Alternatively, use the SDK as shown below or call the API directly.

Run the following setup script to create controls to protect your agent.

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
                "selector": {"path": "output"},
                "evaluator": {
                    "name": "regex",
                    "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
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

Now, test your agent:

```bash
uv run my_agent.py
```

Done. Your agent now blocks SSN patterns automatically.

For detailed explanations of how controls work under the hood, configuration options, and other development setup, see the complete [Quickstart](https://docs.agentcontrol.dev/core/quickstart) guide.

## Performance

| Endpoint         | Scenario                      | RPS     | p50      | p99      |
| ---------------- | ----------------------------- | ------- | -------- | -------- |
| Agent init       | Agent with 3 tool steps       | 509     | 19 ms    | 54 ms    |
| Evaluation       | 1 control, 500-char content   | 437     | 36 ms    | 61 ms    |
| Evaluation       | 10 controls, 500-char content | 349     | 35 ms    | 66 ms    |
| Evaluation       | 50 controls, 500-char content | 199     | 63 ms    | 91 ms    |
| Controls refresh | 5-50 controls per agent       | 273-392 | 20-27 ms | 27-61 ms |

- Agent init handles both create and update identically (upsert).
- All four built-in evaluators (regex, list, JSON, SQL) perform within 40-46 ms p50 at 1 control.
- Moving from 1 to 50 controls increased evaluation p50 by about 27 ms.
- Local laptop benchmarks are directional and intended for developer reference. They are not production sizing guidance.

_Benchmarked on Apple M5 (16 GB RAM), Docker Compose (`postgres:16` + `agent-control`). 2 minutes per scenario, 5 concurrent users for latency (p50, p99), 10-20 for throughput (RPS). RPS = completed requests per second. All scenarios completed with 0% errors._

---

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
