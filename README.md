# Agent Control

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/agent-control-sdk.svg)](https://pypi.org/project/agent-control-sdk/)
[![CI](https://github.com/rungalileo/agent-control/actions/workflows/ci.yml/badge.svg)](https://github.com/rungalileo/agent-control/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/rungalileo/agent-control/branch/main/graph/badge.svg)](https://codecov.io/gh/rungalileo/agent-control)

**Runtime guardrails for AI agents — configurable, extensible, and production-ready.**

AI agents interact with users, tools, and external systems in unpredictable ways. Agent Control provides an extensible, policy-based runtime layer that evaluates inputs and outputs against configurable rules — blocking prompt injections, PII leakage, and other risks without modifying your agent's code.

---

## See It In Action

```python
import agent_control
from agent_control import control, ControlViolationError

# Initialize once at startup
agent_control.init(
    agent_name="Customer Support Agent",
    agent_id="support-agent-v1",
    server_url="http://localhost:8000"
)

# Protect any function with a decorator
@control()
async def chat(message: str) -> str:
    return await llm.generate(message)

# Violations are caught automatically
try:
    response = await chat(user_input)
except ControlViolationError as e:
    print(f"Blocked by control '{e.control_name}': {e.message}")
```

---

## Key Features

- **Safety Without Code Changes** — Add guardrails with a `@control()` decorator
- **Runtime Configuration** — Update controls without redeploying your application
- **Centralized Policies** — Define controls once, apply to multiple agents
- **Web Dashboard** — Manage agents and controls through the UI
- **API Key Authentication** — Secure your control server in production
- **Pluggable Evaluators** — Regex, list matching, AI-powered detection (Luna-2), or custom evaluators
- **Fail-Safe Defaults** — Deny controls fail closed on error; evaluators like Luna-2 support configurable error handling

---

## Quick Start

### Prerequisites

- **Python 3.12+**
- **uv** — Fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Docker** — For running PostgreSQL
- **Node.js 18+** — For the web dashboard (optional)

### 1. Clone and Install

```bash
git clone https://github.com/rungalileo/agent-control.git
cd agent-control
make sync
```

### 2. Start the Server

```bash
# Start database and run migrations
cd server && docker-compose up -d && make alembic-upgrade && cd ..

# Start the server
make server-run
```

Server is now running at `http://localhost:8000`.

### 3. Start the Dashboard (Optional)

```bash
cd ui
pnpm install
pnpm dev
```

Dashboard is now running at `http://localhost:4000`.

### 4. Use the SDK

Install the SDK:

```bash
pip install agent-control
```

Use in your code:

```python
import agent_control
from agent_control import control, ControlViolationError

# Initialize — connects to server and registers agent
agent_control.init(
    agent_name="Customer Support Agent",
    agent_id="support-agent-v1",
    server_url="http://localhost:8000"
)

# Apply controls to any function
@control()
async def chat(message: str) -> str:
    """This function is protected by server-defined controls"""
    return await llm.generate(message)

# Handle violations gracefully
async def main():
    try:
        response = await chat("Hello!")
        print(response)
    except ControlViolationError as e:
        print(f"Blocked by control '{e.control_name}': {e.message}")
```

> **Note**: Authentication is disabled by default for local development. See [docs/REFERENCE.md](docs/REFERENCE.md#authentication) for production setup.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_CONTROL_URL` | `http://localhost:8000` | Server URL for SDK |
| `AGENT_CONTROL_API_KEY` | — | API key for authentication (if enabled) |
| `DB_URL` | `sqlite+aiosqlite:///./agent_control.db` | Database connection string |
| `GALILEO_API_KEY` | — | Required for Luna-2 AI evaluator |

### Server Configuration

The server supports additional environment variables:

- `AGENT_CONTROL_API_KEY_ENABLED` - Enable API key authentication (default: `false`)
- `LOG_LEVEL` - Logging level (default: `INFO`)

See [server/README.md](server/README.md) for complete server configuration.

---

## Defining Controls

Controls are defined via the API or dashboard. Each control specifies what to check and what action to take.

### Example: Block PII in Output (Regex)

```json
{
  "name": "block-ssn-output",
  "description": "Block Social Security Numbers in responses",
  "enabled": true,
  "execution": "server",
  "scope": { "step_types": ["llm"], "stages": ["post"] },
  "selector": { "path": "output" },
  "evaluator": {
    "name": "regex",
    "config": { "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b" }
  },
  "action": { "decision": "deny" }
}
```

### Example: Block Toxic Input (Luna-2 AI)

```json
{
  "name": "block-toxic-input",
  "description": "Block toxic or harmful user messages",
  "enabled": true,
  "execution": "server",
  "scope": { "step_types": ["llm"], "stages": ["pre"] },
  "selector": { "path": "input" },
  "evaluator": {
    "name": "galileo-luna2",
    "config": {
      "metric": "input_toxicity",
      "operator": "gt",
      "target_value": 0.5
    }
  },
  "action": { "decision": "deny" }
}
```

See [docs/REFERENCE.md](docs/REFERENCE.md#evaluators) for full evaluator documentation.

---

## Architecture

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
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │  Controls  │  │  Policies  │  │ Evaluators │  │   Agents   │  │
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
| `agent-control` | Python SDK with `@control()` decorator |
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
├── server/          # FastAPI server (agent-control-server)
├── engine/          # Evaluation engine (agent-control-engine)
├── models/          # Shared models (agent-control-models)
├── evaluators/      # Evaluator implementations (agent-control-evaluators)
├── ui/              # Next.js dashboard
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

### Examples

- **[Examples Overview](examples/README.md)** — Working code examples and integration patterns
- **[Customer Support Agent](examples/customer_support_agent/)** — Full example with multiple tools
- **[LangChain SQL Agent](examples/langchain/)** — SQL injection protection with LangChain
- **[Galileo Luna-2 Integration](examples/galileo/)** — AI-powered toxicity detection

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
