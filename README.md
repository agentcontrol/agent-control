# 🛡️ Agent Control

**A modular, type-safe control system for AI Agents.**

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/galileo-public/agent-control)
[![PyPI version](https://img.shields.io/pypi/v/agent-control)](https://pypi.org/project/agent-control/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Agent Control is a lightweight toolkit for building modular AI pipelines with built-in safety. It isolates control logic from your agent's business logic, providing a dedicated server and SDK to enforce safety policies.

*   **Modular Design**: Decoupled architecture with separate server, engine, and SDK components.
*   **Type-Safe Control**: Uses strict Pydantic models for rule definitions and payloads.
*   **Performance Focused**: Linear-time regex matching (via `google-re2`) to prevent ReDoS attacks.
*   **Flexible Integration**: Works with any Python agent framework (LangChain, LangGraph, etc.) or via HTTP API.
*   **Unified Logic**: Handles AllowList, DenyList, and Regex patterns with a consistent configuration interface.

---

## 🚀 TL;DR Quickstart

**1. Install the SDK**

```bash
pip install agent-control
```

**2. Hello World Example**

```python
import asyncio
import agent_control
from agent_control import control

# Initialize the agent
agent_control.init(
    agent_name="My Demo Agent",
    agent_id="demo-agent-v1"
)

# Protect a function with a control policy
@control(policy='input-check')
async def handle_message(message: str):
    print(f"Processing: {message}")
    return "Safe content processed."

async def main():
    try:
        # If 'rules.yaml' defines 'input-check', this input is validated
        result = await handle_message("Hello World")
        print(result)
    except Exception as e:
        print(f"Blocked: {e}")

if __name__ == "__main__":
    asyncio.run(main())
```

**What This Example Demonstrates**
*   **Simple Initialization**: One-line setup to register your agent.
*   **Decorator Pattern**: Non-intrusive `@control` decorator to enforce rules.
*   **Automatic Validation**: Input is checked against defined policies before execution.

---

## 💡 Why Use This Project?

**Agent Control** is designed for developers who need to add robust safety layers to their AI applications without cluttering their codebase with validation logic.

*   **Build modular AI workflows**: Keep safety rules separate from agent code.
*   **Structure and validate LLM outputs**: Ensure model responses meet strict format and content requirements.
*   **Prevent attacks**: Block prompt injection and unsafe tool usage with pre-built evaluators.
*   **Extend or compose agents**: Easily add control to existing agents in LangChain or other frameworks.
*   **Centralized Management**: Manage rules for multiple agents from a single server/database.

---

## 🧠 Core Concepts / Mental Model

Agent Control is built as a monorepo with four distinct components working together:

```mermaid
graph TD
    Agent[Your Agent] --> SDK[🔧 SDK (agent-control)]
    SDK --> Server[🚀 Server (agent-control-server)]
    Server --> Engine[⚙️ Engine (agent-control-engine)]
    Engine --> Models[📦 Models (agent-control-models)]
```

*   **Models (`agent-control-models`)**: The shared language. Defines strict Pydantic schemas for `LlmCall`, `ToolCall`, `Policy`, and `Control`.
*   **Engine (`agent-control-engine`)**: The brain. Pure logic component that executes evaluators (Regex, AllowList, DenyList). fast and stateless.
*   **Server (`agent-control-server`)**: The hub. A FastAPI server that manages policies, connects to the database, and exposes the Engine via API.
*   **SDK (`agent-control`)**: The client. A Python library that agents use to register themselves and request control checks.
*   **Selector**: A dot-notation string (e.g., `arguments.cmd` or `context.user_id`) used to target specific parts of a payload for validation.

---

## 🛣️ Different Quickstart Paths

### I want to use this in Python (Agent Developer)

Install the client SDK to add control to your Python agents.

```bash
pip install agent-control
```

[View Python SDK Docs](./sdks/python/README.md)

### I want to run the Server (Platform Engineer)

Run the backend server to manage rules and handle requests from multiple agents.

```bash
# Clone and run with Docker
git clone https://github.com/galileo-public/agent-control.git
cd agent-control/server
docker-compose up -d
```

[View Server Docs](./server/README.md)

### I want to extend the library (Contributor)

Add new evaluators, plugins, or features to the core engine.

```bash
# Install uv and sync dependencies
pip install uv
make sync
```

[View Contribution Guide](./CONTRIBUTING.md)

---

## 📦 Installation & Requirements

### Supported Platforms
*   **Python**: 3.12+
*   **OS**: macOS, Linux, Windows (WSL recommended)

### Install from PyPI (Client SDK)

```bash
pip install agent-control
```

### Install from Source (Monorepo)

We recommend using `uv` for dependency management in the monorepo.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and sync
git clone https://github.com/galileo-public/agent-control.git
cd agent-control
make sync
```

---

## 🧪 Examples / Recipes

Check out the `examples/` folder for runnable scripts and integration patterns.

*   [**Basic Usage**](./examples/basic_usage.py): Simple content safety checks.
*   [**Batch Processing**](./examples/batch_processing.py): Concurrent checks for high throughput.
*   [**LangGraph Integration**](./examples/langgraph/README.md): Complete example of a stateful agent with safety gates.
*   [**Direct Model Usage**](./examples/models_usage.py): Working with Pydantic models directly.

---

## ⚙️ Configuration

### Environment Variables

The SDK and Server can be configured via environment variables.

```bash
# SDK Configuration
export AGENT_CONTROL_URL="http://localhost:8000"  # URL of the control server
export AGENT_ID="my-agent-v1"                     # Optional default agent ID

# Server Configuration (in server/.env)
export PORT=8000
export DB_URL="postgresql+asyncpg://user:pass@localhost/db"
```

### Rules Configuration (`controls.yaml`)

Define your control policies in a simple YAML file:

```yaml
input-validation:
  step_id: "input-check"
  description: "Block forbidden words"
  rules:
    - match:
        string: ["forbidden", "banned"]
      action: deny
      data: input
  default_action: allow
```

---

## 🔌 Extending the Project

Agent Control is designed to be extended. You can add custom evaluators or plugins.

### What Can Be Extended
*   **Evaluators**: Add new logic for checking data (e.g., PII detection, sentiment analysis).
*   **Plugins**: Integrate external services (e.g., Galileo Luna, 3rd party APIs).

### Minimal Extension Example (New Evaluator)

To add a new evaluator, create a class in `engine/src/agent_control_engine/evaluators.py`:

```python
from .core import Evaluator, EvaluatorResult

class LengthEvaluator(Evaluator):
    def evaluate(self, data: str, config: dict) -> EvaluatorResult:
        max_len = config.get("max", 100)
        if len(data) > max_len:
            return EvaluatorResult(match=True)
        return EvaluatorResult(match=False)
```

### Where to Put New Code
*   **`engine/`**: Core logic and new evaluators.
*   **`plugins/`**: External integrations.
*   **`models/`**: Shared data structures.

---

## 📂 Project Structure Overview

```text
agent-control/
├── models/          # Shared Pydantic models (agent-control-models)
├── server/          # FastAPI server (agent-control-server)
├── sdks/            # Client SDKs
│   └── python/      # Python SDK (agent-control)
├── engine/          # Core evaluation logic (agent-control-engine)
├── plugins/         # Plugin system (agent-control-plugins)
├── examples/        # Usage examples and tutorials
└── tests/           # Integration tests
```

*   **`models`**: The source of truth for API contracts.
*   **`engine`**: pure-python logic, no network/DB dependencies.
*   **`server`**: The deployment artifact.
*   **`sdks`**: What users actually install.

---

## 🛠 Development & Contribution Guide

We welcome contributions! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed instructions.

**Development Setup**

```bash
# 1. Clone and sync
make sync

# 2. Run tests
make test

# 3. Lint and format
make lint
```

**Workflow**
*   Use `make check` to run all quality checks before pushing.
*   Follow Conventional Commits for PR titles.

---

## 🗺️ Roadmap / Stability Notes

**Current Status**: **Experimental (v0.1.0)**.
APIs may change. Suitable for testing and development environments.

**Upcoming Features**:
*   [ ] Advanced PII Redaction
*   [ ] Streaming Response Support
*   [ ] Webhook Alerts
*   [ ] Distributed Caching

---

## ❓ FAQ / Troubleshooting

**Q: Why is the server separate from the SDK?**
A: To decouple safety logic from application logic. This allows you to update rules without redeploying agents and manage policies centrally.

**Q: How do I run this locally without Docker?**
A: You can run the server directly if you have a Postgres DB available:
```bash
cd server
export DB_URL="..."
uv run python -m agent_control_server.main
```

**Q: "Connection refused" when using the SDK?**
A: Ensure the server is running (`curl http://localhost:8000/health`) and `AGENT_CONTROL_URL` is set correctly.

---

## 📄 License and Credits

This project is licensed under the **Apache 2.0 License**.

**Acknowledgements**:
*   Built with [FastAPI](https://fastapi.tiangolo.com/), [Pydantic](https://docs.pydantic.dev/), and [uv](https://github.com/astral-sh/uv).
