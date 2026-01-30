# Contributing to Agent Control

Thanks for contributing! This document covers conventions, setup, and workflows for all contributors.

## Project Architecture

Agent Control is a **uv workspace monorepo** with these components:

```
agent-control/
├── models/          # Shared Pydantic models (agent-control-models)
├── server/          # FastAPI server (agent-control-server)
├── sdks/python/     # Python SDK (agent-control)
├── engine/          # Control evaluation engine (agent-control-engine)
├── evaluators/      # Evaluator implementations (agent-control-evaluators)
└── examples/        # Usage examples
```

**Dependency flow:**
```
SDK ──────────────────────────────────────┐
                                          ▼
Server ──► Engine ──► Models ◄── Evaluators
```

---

## Development Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker (for server database)

### Initial Setup

```bash
# Clone the repository
git clone <repo-url>
cd agent-control

# Install all dependencies (creates single .venv for workspace)
make sync

# Install git hooks (recommended)
make hooks-install
```

---

## Working with Components

### Models (`models/`)

Shared Pydantic models used by both server and SDK.

```bash
# Location
models/src/agent_control_models/

# Key files
├── agent.py       # Agent, Step models
├── controls.py    # Control definitions, evaluators
├── evaluation.py  # EvaluationRequest/Response
├── policy.py      # Policy model
└── health.py      # Health response
```

**When to modify:**
- Adding new API request/response models
- Changing shared data structures
- Adding validation rules

**Testing:**
```bash
cd models
uv run pytest
```

---

### Server (`server/`)

FastAPI server providing the Agent Control API.

```bash
# Location
server/src/agent_control_server/

# Key files
├── main.py        # FastAPI app entrypoint
├── endpoints/     # API route handlers
├── services/      # Business logic
└── db/            # Database models & queries
```

**Running the server:**
```bash
cd server

# Start dependencies (PostgreSQL via Docker)
make start-dependencies

# Run database migrations
make alembic-upgrade

# Start server with hot-reload
make run
```

**Database migrations:**
```bash
cd server

# Create new migration
make alembic-migrate MSG="add new column"

# Apply migrations
make alembic-upgrade

# Rollback one migration
make alembic-downgrade

# View migration history
make alembic-history
```

**Testing:**
```bash
cd server
make test
```

---

### SDK (`sdks/python/`)

Python client SDK for interacting with the Agent Control server.

```bash
# Location
sdks/python/src/agent_control/

# Key files
├── __init__.py           # Public API exports, init() function
├── client.py             # AgentControlClient (HTTP client)
├── agents.py             # Agent registration operations
├── policies.py           # Policy management
├── controls.py           # Control management
├── control_sets.py       # Control set management
├── evaluation.py         # Evaluation checks
├── control_decorators.py # @control decorator
└── evaluators/           # Evaluator system
```

**Key exports:**
```python
import agent_control

# Initialization
agent_control.init(agent_name="...", agent_id="...")

# Decorator
@agent_control.control()
async def my_function(): ...

# Client
async with agent_control.AgentControlClient() as client:
    await agent_control.agents.get_agent(client, "id")
```

**Testing:**
```bash
cd sdks/python
make test  # Starts server automatically
```

**Adding new SDK functionality:**
1. Add operation function in appropriate module (e.g., `policies.py`)
2. Export in `__init__.py` if needed
3. Add tests in `tests/`
4. Update docstrings with examples

---

### Engine (`engine/`)

Core control evaluation logic. The engine loads evaluators and executes evaluations.

```bash
# Location
engine/src/agent_control_engine/

# Key files
├── core.py        # Main ControlEngine class
├── evaluators.py  # Evaluator loader and caching
└── selectors.py   # Data selection from payloads
```

**How it works:**
- The engine uses the evaluator registry to find evaluators
- Evaluators are cached for performance (LRU cache)
- Selectors extract data from payloads before evaluation

**Testing:**
```bash
cd engine
make test
```

> **Note:** To add new evaluators, create an evaluator in `evaluators/` rather than modifying the engine directly. See the Evaluators section below.

---

### Evaluators (`evaluators/`)

Extensible evaluators for custom detection logic.

```bash
# Location
evaluators/src/agent_control_evaluators/

# Key directories (flat structure - each evaluator is a peer directory)
# Built-in evaluators (no namespace, core dependencies only)
├── regex/           # Type name: "regex"
│   ├── config.py    # RegexEvaluatorConfig
│   └── evaluator.py # RegexEvaluator implementation
├── list/            # Type name: "list"
│   ├── config.py    # ListEvaluatorConfig
│   └── evaluator.py # ListEvaluator implementation
├── json/            # Type name: "json"
│   ├── config.py    # JsonEvaluatorConfig
│   └── evaluator.py # JsonEvaluator implementation
├── sql/             # Type name: "sql"
│   ├── config.py    # SqlEvaluatorConfig
│   └── evaluator.py # SqlEvaluator implementation
#
# External evaluators (namespaced, optional dependencies)
└── galileo_luna2/   # Type name: "galileo/luna2" (folder uses underscore)
    ├── config.py    # Luna2EvaluatorConfig
    ├── evaluator.py # Luna2Evaluator implementation
    └── client.py    # Direct HTTP client (no SDK dependency)
```

> **Note:** Folder names use `snake_case` (Python convention), but type names in metadata
> use `provider/name` format with slash for external evaluators.

**Creating a new evaluator:**

Choose the appropriate type based on your use case:

| Type | When to Use | Name Format |
|------|-------------|-------------|
| Built-in | Core functionality, no external deps | `my-evaluator` |
| External | External provider integration, optional deps | `provider/name` |
| Agent-scoped | Custom logic deployed with agent | `my-agent:custom` |

### Creating a Third-Party Evaluator (Recommended for External Providers)

This example creates a external evaluator `acme/toxicity`:

**1. Create evaluator directory:**
```bash
mkdir -p evaluators/src/agent_control_evaluators/acme_toxicity/
touch evaluators/src/agent_control_evaluators/acme_toxicity/__init__.py
```

**2. Define configuration model (`config.py`):**
```python
from pydantic import Field
from agent_control_evaluators import EvaluatorConfig


class AcmeToxicityEvaluatorConfig(EvaluatorConfig):
    """Configuration for Acme Toxicity evaluator."""

    threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Score threshold for triggering (0.0-1.0)",
    )
    categories: list[str] = Field(
        default_factory=lambda: ["hate", "violence"],
        description="Toxicity categories to check",
    )
    timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=30000,
        description="API timeout in milliseconds",
    )
```

**3. Implement evaluator (`evaluator.py`):**
```python
from typing import Any

from agent_control_models import EvaluatorResult

from agent_control_evaluators._base import Evaluator, EvaluatorMetadata
from agent_control_evaluators._registry import register_evaluator
from agent_control_evaluators.acme_toxicity.config import AcmeToxicityEvaluatorConfig

# Check optional dependency
try:
    import httpx
    ACME_AVAILABLE = True
except ImportError:
    ACME_AVAILABLE = False


@register_evaluator
class AcmeToxicityEvaluator(Evaluator[AcmeToxicityEvaluatorConfig]):
    """Acme Toxicity detection evaluator.

    Calls the Acme API to detect toxic content in text.

    Example config:
        {"threshold": 0.8, "categories": ["hate", "harassment"]}
    """

    metadata = EvaluatorMetadata(
        name="acme/toxicity",  # <-- External provider with slash
        version="1.0.0",
        description="Acme toxicity detection API",
        requires_api_key=True,
        timeout_ms=5000,
    )
    config_model = AcmeToxicityConfig

    @classmethod
    def is_available(cls) -> bool:
        """Check if httpx dependency is installed."""
        return ACME_AVAILABLE

    def __init__(self, config: AcmeToxicityEvaluatorConfig) -> None:
        super().__init__(config)
        # Pre-compile or initialize resources here (will be cached)
        self._client: httpx.AsyncClient | None = None

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate text for toxicity."""
        if data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No data to evaluate",
            )

        text = str(data)

        try:
            score = await self._call_api(text)
            matched = score >= self.config.threshold

            return EvaluatorResult(
                matched=matched,
                confidence=score,
                message=f"Toxicity score: {score:.2f}",
                metadata={
                    "score": score,
                    "threshold": self.config.threshold,
                    "categories": self.config.categories,
                },
            )
        except Exception as e:
            # Return error result (fail-open by default)
            return EvaluatorResult(
                matched=False,
                confidence=0.0,
                message=f"Evaluation failed: {e}",
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )

    async def _call_api(self, text: str) -> float:
        """Call Acme API and return toxicity score."""
        # Implementation details...
        pass
```

**4. Export in `__init__.py`:**
```python
from agent_control_evaluators.acme_toxicity.config import AcmeToxicityEvaluatorConfig
from agent_control_evaluators.acme_toxicity.evaluator import AcmeToxicityEvaluator

__all__ = ["AcmeToxicityEvaluator", "AcmeToxicityEvaluatorConfig"]
```

**5. Register entry point in `evaluators/pyproject.toml`:**
```toml
[project.optional-dependencies]
acme = ["httpx>=0.24.0"]  # Your dependencies
all = ["httpx>=0.24.0"]   # Include in 'all' extra

[project.entry-points."agent_control.evaluators"]
regex = "agent_control_evaluators.regex:RegexEvaluator"
list = "agent_control_evaluators.list:ListEvaluator"
# ... existing entries ...
"acme/toxicity" = "agent_control_evaluators.acme_toxicity:AcmeToxicityEvaluator"
```

**6. Add tests in `evaluators/tests/acme_toxicity/`**

### Creating a Built-in Evaluator

For evaluators with no external dependencies (to be included in core), follow the same pattern but:
- Use simple name: `name="my-evaluator"` (no slash)
- No `is_available()` override needed
- Import directly in `evaluators/src/agent_control_evaluators/__init__.py` for auto-registration:
  ```python
  from agent_control_evaluators.my_evaluator import MyEvaluator, MyEvaluatorConfig
  ```

### Evaluator Best Practices

**Thread Safety & Caching:**
- Evaluator instances are **cached and reused** across requests
- **DO NOT** store mutable request-scoped state on `self`
- Use local variables in `evaluate()` for request-specific data
- Initialize immutable resources in `__init__()` (compiled patterns, clients)

**Error Handling:**
- Set `error` field for evaluator failures (API errors, timeouts)
- Return `matched=False` when `error` is set (fail-open)
- DO NOT set `error` for validation failures (bad input is a valid "matched" result)

**Performance:**
- Pre-compile patterns in `__init__()`
- Use `asyncio.to_thread()` for CPU-bound work (see SQL evaluator)
- Respect `timeout_ms` config for external API calls

**Config Validation:**
- Extend `EvaluatorConfig` (not plain `BaseModel`)
- Use Pydantic validators for complex rules
- Provide sensible defaults with `Field(default=...)`

---

## Code Quality

### Linting (Ruff)

```bash
# Check all packages
make lint

# Auto-fix issues
make lint-fix

# Single package
cd server && make lint
```

### Type Checking (mypy)

```bash
# Check all packages
make typecheck

# Single package
cd sdks/python && make typecheck
```

### Pre-push Checks

```bash
# Run all checks (test + lint + typecheck)
make check

# Or manually run pre-push hook
make prepush
```

---

## Testing Conventions

Write tests using **Given/When/Then** comments:

```python
def test_create_control(client: TestClient) -> None:
    # Given: a valid control payload
    payload = {"name": "pii-protection"}

    # When: creating the control via API
    response = client.put("/api/v1/controls", json=payload)

    # Then: the control is created successfully
    assert response.status_code == 200
    assert "control_id" in response.json()
```

**Guidelines:**
- Keep tests small and focused
- Use explicit setup over hidden fixtures
- Test both success and error cases
- Mock external services (database, Galileo API)

---

## Building & Publishing

### Build Packages

```bash
# Build all
make build

# Build individual packages
make build-models
make build-server
make build-sdk
cd engine && make build
```

### Publish Packages

```bash
# Publish all (requires PyPI credentials)
make publish

# Publish individual packages
make publish-models
make publish-server
make publish-sdk
```

**Version bumping:**
Update `version` in respective `pyproject.toml` files:
- `models/pyproject.toml`
- `server/pyproject.toml`
- `sdks/python/pyproject.toml`
- `engine/pyproject.toml`
- `evaluators/pyproject.toml`

---

## Git Workflow

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `refactor/description` - Code refactoring

### Commit Messages

Use conventional commits:
```
feat: add policy assignment endpoint
fix: handle missing agent gracefully
refactor: extract evaluator logic to engine
docs: update SDK usage examples
test: add control set integration tests
```

### Pull Request Checklist

- [ ] Tests pass (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] Type checking passes (`make typecheck`)
- [ ] Documentation updated if needed
- [ ] Examples updated if API changed

---

## Common Tasks

### Add a new API endpoint

1. Add Pydantic models in `models/` if needed
2. Add route handler in `server/src/agent_control_server/endpoints/`
3. Add service logic in `server/src/agent_control_server/services/`
4. Add SDK wrapper in `sdks/python/src/agent_control/`
5. Add tests for both server and SDK
6. Update examples if user-facing

### Add a new evaluator

See the **Evaluators** section above for detailed instructions. Summary:

1. Decide on evaluator type (built-in vs external)
2. Create directory: `evaluators/src/agent_control_evaluators/my_evaluator/`
3. Add `config.py` extending `EvaluatorConfig`
4. Add `evaluator.py` with `@register_evaluator` decorator
5. Add entry point in `evaluators/pyproject.toml`:
   - Built-in: `my-evaluator = "..."`
   - External: `"provider/name" = "..."`
6. Add optional dependencies if needed
7. Add tests in `evaluators/tests/`
8. Update `docs/OVERVIEW.md` with usage examples

### Update shared models

1. Modify models in `models/src/agent_control_models/`
2. Run tests across all packages: `make test`
3. Update any affected server endpoints
4. Update SDK if client-facing

---

## Quick Reference

| Task | Command |
|------|---------|
| Install dependencies | `make sync` |
| Run server | `cd server && make run` |
| Run all tests | `make test` |
| Run linting | `make lint` |
| Run type checks | `make typecheck` |
| Run all checks | `make check` |
| Build packages | `make build` |
| Database migration | `cd server && make alembic-migrate MSG="..."` |

---

## Evaluator Naming Conventions

### Terminology

There are three distinct concepts related to evaluators:

| Concept | Definition | Example |
|---------|------------|---------|
| **Evaluator Type** | An implementation class with `evaluate()` method | `RegexEvaluator`, `Luna2Evaluator` |
| **Evaluator Schema** | Metadata about a custom type (name + JSON Schema for config validation) | Registered via `initAgent` |
| **Evaluator Config** | A saved configuration template (type + specific config values) | Stored via `/evaluator-configs` API |

### Evaluator Type Name Formats

Evaluator type names identify evaluator implementations. The format indicates the evaluator's origin:

| Format | Origin | Examples |
|--------|--------|----------|
| `name` | Built-in (first-party, no dependencies) | `regex`, `list`, `json`, `sql` |
| `provider/name` | External (external providers, optional deps) | `galileo/luna2`, `nvidia/nemo` |
| `agent:name` | Agent-scoped (custom code deployed with agent) | `my-agent:pii-detector` |

**Parsing rules:**
```python
if ":" in name:    # Agent-scoped (split on first ":")
    agent, evaluator = name.split(":", 1)
elif "/" in name:  # External provider (split on first "/")
    provider, evaluator = name.split("/", 1)
else:              # Built-in
    evaluator = name
```

### Built-in vs Third-Party Evaluators

**Built-in evaluators** (`regex`, `list`, `json`, `sql`):
- No namespace prefix
- Core dependencies only (included in base package)
- Imported and registered automatically on package import

**External evaluators** (`galileo/luna2`):
- Use `provider/name` format with slash separator
- Have optional dependencies (install via extras: `pip install agent-control-evaluators[luna2]`)
- Discovered via Python entry points (not auto-imported)

### Agent-Scoped Evaluators

Agent-scoped evaluators (`my-agent:pii-detector`) are custom evaluator types that:
1. Are **implemented in the agent's code** (not in the evaluators package)
2. Have their **schema registered via `initAgent`** for config validation
3. Are **server-only** (SDK cannot run them locally)

```
Agent Code                          Server Database
┌─────────────────────┐            ┌─────────────────────────────┐
│ @register_evaluator │  initAgent │ Agent: "my-agent"           │
│ class PIIDetector   │ ─────────► │ Schemas: [{                 │
│   ...               │            │   name: "pii-detector",     │
└─────────────────────┘            │   config_schema: {...}      │
                                   │ }]                          │
                                   └─────────────────────────────┘
```

Controls reference them as `my-agent:pii-detector` (the `:` indicates agent scope).

### Folder and File Naming

| Item | Convention | Example |
|------|------------|---------|
| Folder name | `snake_case` (Python package) | `galileo_luna2/` |
| Entry point key | Same as type name | `"galileo/luna2"` |
| Metadata name | Same as type name | `name="galileo/luna2"` |

> **Note:** In code, use "provider" as the type identifier. In user-facing docs,
> use "external" as the descriptive term.

---

## Evaluator Development Quick Reference

| Task | Location |
|------|----------|
| Evaluator base class | `agent_control_evaluators.Evaluator` |
| Config base class | `agent_control_evaluators.EvaluatorConfig` |
| Evaluator metadata | `agent_control_evaluators.EvaluatorMetadata` |
| Evaluator result | `agent_control_models.EvaluatorResult` |
| Register decorator | `@agent_control_evaluators.register_evaluator` |
| Built-in evaluators | `evaluators/src/agent_control_evaluators/{regex,list,json,sql}/` |
| External evaluators | `evaluators/src/agent_control_evaluators/galileo_luna2/` |
| Evaluator tests | `evaluators/tests/` |

**Naming convention quick reference:**
```
Built-in:      regex, list, json, sql
External:   galileo/luna2, nvidia/nemo
Agent-scoped:  my-agent:pii-detector
```

**Evaluator config model fields:**
```python
from pydantic import Field
from agent_control_evaluators import EvaluatorConfig

class MyEvaluatorConfig(EvaluatorConfig):
    # Required field
    pattern: str = Field(..., description="Pattern to match")

    # Optional with default
    threshold: float = Field(0.5, ge=0.0, le=1.0)

    # List field
    values: list[str] = Field(default_factory=list)
```

**EvaluatorResult fields:**
```python
EvaluatorResult(
    matched=True,           # Did this trigger the control?
    confidence=0.95,        # How confident (0.0-1.0)?
    message="Explanation",  # Human-readable message
    metadata={"key": "val"} # Additional context
)
```

---

## Need Help?

- **Documentation:** See `docs/OVERVIEW.md` for architecture overview
- **Examples:** Check `examples/` for usage patterns
- **Tests:** Look at existing tests for patterns to follow
