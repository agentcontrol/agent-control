# 🛡️ Agent Control

**Runtime guardrails for AI agents — configurable, extensible, and production-ready.**

Agent Control provides a policy-based control layer that sits between your AI agents and the outside world. It evaluates inputs and outputs against configurable rules, blocking harmful content, prompt injections, PII leakage, and other risks — all without changing your agent's code.

---

## 🏗 Architecture

Agent Control is built as a monorepo with five distinct components:

```
┌──────────────────────────────────────────────────────────────────┐
│                         Your Application                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                     @control() decorator                    │  │
│  │                            │                                │  │
│  │                            ▼                                │  │
│  │  ┌──────────┐    ┌─────────────────┐    ┌──────────────┐   │  │
│  │  │  Input   │───▶│  Agent Control  │───▶│    Output    │   │  │
│  │  │          │    │     Engine      │    │              │   │  │
│  │  └──────────┘    └─────────────────┘    └──────────────┘   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Agent Control Server                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │  Controls  │  │  Policies  │  │  Plugins   │  │   Agents   │  │
│  │    API     │  │    API     │  │  Registry  │  │    API     │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Plugin Ecosystem                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │   Regex    │  │    List    │  │   Luna-2   │  │   Custom   │  │
│  │ Evaluator  │  │ Evaluator  │  │   Plugin   │  │  Plugins   │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

| Package | Description |
| :--- | :--- |
| **`agent-control-models`** | Shared **Pydantic v2** models for strict type safety across the stack. |
| **`agent-control-engine`** | Core evaluation logic. Uses `google-re2` for safe regex and plugin system. |
| **`agent-control-server`** | FastAPI server that hosts the engine and provides a Control Management API. |
| **`agent-control`** | Python SDK for agents to register and enforce controls via decorators. |
| **`agent-control-plugins`** | Extensible evaluator plugins (regex, list, Luna-2, custom). |

---

## ✨ Key Features

- **🛡️ Safety Without Code Changes**: Add guardrails with a simple `@control()` decorator.
- **⚡ Runtime Configuration**: Update controls without redeploying your application.
- **🎯 Centralized Policies**: Define controls once, apply to multiple agents.
- **📊 Full Observability**: Every evaluation logged with trace IDs and metadata.
- **🔌 Pluggable Evaluators**: Regex, list matching, AI-powered detection (Luna-2), or custom plugins.
- **⚖️ Configurable Risk**: Choose fail-open or fail-closed behavior.

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.12+**
- **uv**: Fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Docker**: For running the database (PostgreSQL)

### 2. Setup

```bash
# Clone repo
git clone https://github.com/rungalileo/agent-control.git
cd agent-control

# Sync dependencies for all workspaces
make sync

# Start database
cd server && docker-compose up -d
make alembic-upgrade
```

### 3. Run the Server

```bash
# From repo root
make server-run
```
Server is now running at `http://localhost:8000`.

### 4. Use the SDK

```python
import agent_control
from agent_control import control

# Initialize at startup
agent_control.init(
    agent_name="my-agent",
    server_url="http://localhost:8000"
)

# Protect your agent with a decorator
@control()
async def chat(message: str) -> str:
    return await llm.generate(message)
```

---

## 📖 Usage Guide

### Defining Controls

Controls are defined via the API using JSON that matches our Pydantic models.

#### Example: Block dangerous commands (List evaluator)
```json
{
  "description": "Block dangerous commands",
  "enabled": true,
  "applies_to": "tool_call",
  "check_stage": "pre",
  "selector": { "path": "arguments.cmd" },
  "evaluator": {
    "plugin": "list",
    "config": {
      "values": ["rm", "shutdown", "reboot"],
      "logic": "any",
      "match_on": "match"
    }
  },
  "action": { "decision": "deny" }
}
```

#### Example: Detect PII via Regex
```json
{
  "description": "Block SSN in output",
  "applies_to": "llm_call",
  "check_stage": "post",
  "selector": { "path": "output" },
  "evaluator": {
    "plugin": "regex",
    "config": {
      "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b"
    }
  },
  "action": { "decision": "deny" }
}
```

#### Example: Block toxic content (Luna-2 plugin)
```json
{
  "description": "Block toxic inputs",
  "applies_to": "llm_call",
  "check_stage": "pre",
  "selector": { "path": "input" },
  "evaluator": {
    "plugin": "galileo-luna2",
    "config": {
      "metric": "input_toxicity",
      "operator": "gt",
      "target_value": 0.5
    }
  },
  "action": { "decision": "deny" }
}
```

### Built-in Evaluators

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `regex` | Pattern matching (RE2) | PII detection, secret scanning |
| `list` | Value matching with flexible logic | Blocklists, allowlists, keywords |
| `galileo-luna2` | AI-powered detection | Toxicity, prompt injection, hallucination |

### Selector Options

| Path | Description |
|------|-------------|
| `input` | User input text |
| `output` | Agent response |
| `arguments.query` | Tool argument |
| `tool_name` | Name of tool being called |
| `context.user_id` | Context field |
| `*` | Entire payload (default) |

### Action Options

| Action | Behavior |
|--------|----------|
| `deny` | Block the request/response |
| `allow` | Explicitly permit |
| `warn` | Log warning but allow |
| `log` | Silent logging only |

---

## 🛠 Development

### Commands (`Makefile`)

| Command | Description |
| :--- | :--- |
| `make sync` | Sync dependencies for all packages |
| `make test` | Run tests across all packages |
| `make lint` | Run `ruff` linting |
| `make typecheck` | Run `mypy` static type checking |
| `make check` | Run all quality checks (test + lint + typecheck) |
| `make server-run` | Start the server |

### Directory Structure

```
agent-control/
├── models/          # Shared Pydantic models (agent-control-models)
├── engine/          # Control evaluation engine (agent-control-engine)
├── server/          # FastAPI server (agent-control-server)
├── sdks/python/     # Python SDK (agent-control)
├── plugins/         # Plugin implementations (agent-control-plugins)
└── examples/        # Usage examples
```

---

## 📚 Documentation

- **[Overview](docs/OVERVIEW.md)** — Detailed architecture and concepts
- **[Contributing](CONTRIBUTING.md)** — Development setup and guidelines
- **[Testing](docs/testing.md)** — Testing conventions

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch
3. Make changes (ensure `make check` passes)
4. Submit a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## 📄 License

Apache 2.0 — See [LICENSE](LICENSE) for details.
