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
├── plugins/         # Plugin implementations (agent-control-plugins)
└── examples/        # Usage examples
```

**Dependency flow:**
```
SDK ──────────────────────────────────────┐
                                          ▼
Server ──► Engine ──► Models ◄── Plugins
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
└── plugins/              # Plugin system
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

Core control evaluation logic. The engine loads plugins and executes evaluations.

```bash
# Location
engine/src/agent_control_engine/

# Key files
├── core.py        # Main ControlEngine class
├── evaluators.py  # Plugin loader and caching
└── selectors.py   # Data selection from payloads
```

**How it works:**
- The engine uses the plugin registry to find evaluators
- Plugins are cached for performance (LRU cache)
- Selectors extract data from payloads before evaluation

**Testing:**
```bash
cd engine
make test
```

> **Note:** To add new evaluators, create a plugin in `plugins/` rather than modifying the engine directly. See the Plugins section above.

---

### Plugins (`plugins/`)

Extensible evaluator plugins for custom detection logic.

```bash
# Location
plugins/src/agent_control_plugins/

# Key directories
├── base.py        # PluginEvaluator base class
├── builtin/       # Built-in evaluators
│   ├── regex.py   # RegexPlugin - pattern matching
│   └── list.py    # ListPlugin - value matching
└── luna2/         # Galileo Luna-2 integration
    ├── plugin.py  # Luna2Plugin implementation
    ├── config.py  # Luna2Config model
    └── client.py  # Direct HTTP client (no SDK dependency)
```

**Adding a new plugin:**

1. **Create plugin directory:**
   ```bash
   mkdir plugins/src/agent_control_plugins/my_plugin/
   ```

2. **Define configuration model (`config.py`):**
   ```python
   from pydantic import BaseModel, Field

   class MyPluginConfig(BaseModel):
       """Configuration for MyPlugin."""
       threshold: float = Field(0.5, ge=0.0, le=1.0)
       api_endpoint: str = Field(default="https://api.example.com")
   ```

3. **Implement plugin (`plugin.py`):**
   ```python
   from typing import Any
   from agent_control_models import (
       EvaluatorResult,
       PluginEvaluator,
       PluginMetadata,
       register_plugin,
   )
   from .config import MyPluginConfig

   @register_plugin
   class MyPlugin(PluginEvaluator[MyPluginConfig]):
       """My custom evaluator plugin."""
       
       metadata = PluginMetadata(
           name="my-plugin",
           version="1.0.0",
           description="Custom detection logic",
           requires_api_key=False,
           timeout_ms=5000,
       )
       config_model = MyPluginConfig

       def __init__(self, config: MyPluginConfig) -> None:
           super().__init__(config)
           # Initialize any clients or resources

       async def evaluate(self, data: Any) -> EvaluatorResult:
           # Your detection logic here
           score = await self._analyze(str(data))
           
           return EvaluatorResult(
               matched=score > self.config.threshold,
               confidence=score,
               message=f"Analysis score: {score:.2f}",
               metadata={"score": score},
           )
   ```

4. **Export in `__init__.py`:**
   ```python
   from .config import MyPluginConfig
   from .plugin import MyPlugin

   __all__ = ["MyPlugin", "MyPluginConfig"]
   ```

5. **Add optional dependencies in `plugins/pyproject.toml`:**
   ```toml
   [project.optional-dependencies]
   my-plugin = ["httpx>=0.24.0"]  # Add your dependencies
   all = ["httpx>=0.24.0", ...]   # Include in 'all' extra
   ```

6. **Add tests in `plugins/tests/`**

**Plugin Best Practices:**
- Use Pydantic for config validation
- Make API calls async with httpx
- Return confidence scores (0.0-1.0)
- Include helpful metadata for debugging
- Handle errors gracefully (respect `on_error` config)
- Avoid storing request-scoped state (plugins are cached)

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
- `plugins/pyproject.toml`

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

### Add a new evaluator plugin

1. Create plugin directory in `plugins/src/agent_control_plugins/`
2. Implement `PluginEvaluator` interface (see Plugins section above)
3. Add `@register_plugin` decorator to your plugin class
4. Add optional dependencies in `plugins/pyproject.toml`
5. Export from `plugins/src/agent_control_plugins/__init__.py`
6. Add tests in `plugins/tests/`
7. Update `docs/OVERVIEW.md` with usage examples

### Add a built-in evaluator (regex/list style)

1. Add evaluator class in `plugins/src/agent_control_plugins/builtin/`
2. Add config model in `models/src/agent_control_models/controls.py`
3. Register with `@register_plugin` decorator
4. Add comprehensive tests in `plugins/tests/`

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

## Plugin Development Quick Reference

| Task | Location |
|------|----------|
| Plugin base class | `agent_control_models.PluginEvaluator` |
| Plugin metadata | `agent_control_models.PluginMetadata` |
| Evaluator result | `agent_control_models.EvaluatorResult` |
| Register decorator | `@agent_control_models.register_plugin` |
| Built-in plugins | `plugins/src/agent_control_plugins/builtin/` |
| Plugin tests | `plugins/tests/` |

**Plugin config model fields:**
```python
from pydantic import BaseModel, Field

class MyConfig(BaseModel):
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
