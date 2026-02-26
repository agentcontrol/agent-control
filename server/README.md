# Agent Control Server

FastAPI server for Agent Control - provides centralized control management, policy enforcement, and evaluation services via REST API.

## Features

- **Control Management** - CRUD operations for controls
- **Policy Management** - Group controls into reusable policies
- **Agent Registration** - Register and manage agents
- **Evaluation Engine** - Server-side control evaluation with evaluator support
- **Observability** - Event tracking and control execution metrics
- **API Key Authentication** - Secure production deployments
- **Evaluator System** - Extensible evaluators (Regex, List, SQL, Luna-2 AI)
- **Prometheus Metrics** - Built-in monitoring and observability
- **PostgreSQL/SQLite** - Production and development database support

## Installation

### For Development (within monorepo)

```bash
# From the root directory
uv sync

# Start database (PostgreSQL)
cd server
docker-compose up -d

# Run migrations
make alembic-upgrade

# Run the server
make run
# Or: uv run uvicorn agent_control_server.main:app --reload
```

### For Production Deployment

```bash
# Build the package
cd server
uv build

# Install the built package
uv pip install dist/agent_control_server-*.whl

# Run the server
agent-control-server
```

## Configuration

Create a `.env` file in the server directory:

```env
# Database (use DATABASE_URL for Docker, DB_URL for local dev)
DATABASE_URL=postgresql+psycopg://user:password@localhost/agent_control
# Or use DB_URL (legacy):
# DB_URL=postgresql+psycopg://user:password@localhost/agent_control
# Or for development:
# DB_URL=sqlite+aiosqlite:///./agent_control.db

# Server settings
HOST=0.0.0.0
PORT=8000
DEBUG=false

# Authentication
AGENT_CONTROL_API_KEY_ENABLED=true
AGENT_CONTROL_API_KEYS=your-api-key-here,another-key-here

# Observability
OBSERVABILITY_ENABLED=true
OBSERVABILITY_FLUSH_INTERVAL_SECONDS=10

# Luna-2 Evaluator (optional)
GALILEO_API_KEY=your-galileo-api-key

# Prometheus metrics
PROMETHEUS_METRICS_PREFIX=agent_control_server
```

## Authentication

The Agent Control Server supports API key authentication via the `X-API-Key` header.

### Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `AGENT_CONTROL_API_KEY_ENABLED` | Enable/disable authentication | `false` |
| `AGENT_CONTROL_API_KEYS` | Comma-separated list of valid API keys | (none) |
| `AGENT_CONTROL_ADMIN_API_KEYS` | Comma-separated list of admin API keys | (none) |

### Access Levels

| Level | Endpoints | Key Type |
|-------|-----------|----------|
| Public | `/health` | None required |
| Protected | All `/api/v1/*` endpoints | Regular or Admin |

### Key Rotation

Multiple API keys are supported to enable zero-downtime key rotation:

1. Add the new key to `AGENT_CONTROL_API_KEYS`
2. Update clients to use the new key  
3. Remove the old key from `AGENT_CONTROL_API_KEYS`
4. Redeploy the server

### Example Usage

```bash
# With curl
curl -H "X-API-Key: your-api-key" http://localhost:8000/api/v1/agents/...

# With Python SDK
from agent_control import AgentControlClient

async with AgentControlClient(api_key="your-api-key") as client:
    await client.health_check()

# Or via environment variable
export AGENT_CONTROL_API_KEY="your-api-key"
async with AgentControlClient() as client:
    await client.health_check()
```

### Disabling Authentication

For local development, you can disable authentication:

```env
AGENT_CONTROL_API_KEY_ENABLED=false
```

**Warning**: Never disable authentication in production environments.

## API Endpoints

All protected endpoints require `X-API-Key` header when authentication is enabled.

### System Endpoints

```bash
# Health check (public)
GET /health

# Prometheus metrics (public)
GET /metrics

# List available evaluators
GET /api/v1/evaluators
```

### Agent Management

```bash
# Register or update agent
POST /api/v1/agents/init
Body: { "agent": {...}, "tools": [...], "force_replace": false }

# Get agent
GET /api/v1/agents/{agent_id}

# List controls for agent (based on assigned policy)
GET /api/v1/agents/{agent_id}/controls
```

### Control Management

```bash
# Create control
POST /api/v1/controls
Body: { "control": {...} }

# List controls
GET /api/v1/controls?skip=0&limit=100

# Get control
GET /api/v1/controls/{control_id}

# Update control
PUT /api/v1/controls/{control_id}
Body: { "control": {...} }

# Delete control
DELETE /api/v1/controls/{control_id}
```

### Policy Management

```bash
# Create policy
POST /api/v1/policies
Body: { "name": "my-policy", "description": "..." }

# List policies
GET /api/v1/policies

# Assign policy to agent
POST /api/v1/policies/{policy_id}/agents/{agent_id}

# Add control to policy
POST /api/v1/policies/{policy_id}/controls/{control_id}
```

### Evaluation

```bash
# Evaluate step against controls
POST /api/v1/evaluation
Body: {
  "agent_uuid": "uuid",
  "step": { "type": "llm", "name": "chat", "input": "..." },
  "stage": "pre"
}

Response: {
  "is_safe": true,
  "confidence": 1.0,
  "matches": [],
  "errors": []
}
```

### Observability

```bash
# Submit events
POST /api/v1/observability/events
Body: { "events": [...] }

# Query events
POST /api/v1/observability/events/query
Body: { "agent_uuid": "...", "start_time": "...", ... }

# Get agent stats
GET /api/v1/observability/stats?agent_uuid=...&time_range=5m

# Get control stats
GET /api/v1/observability/stats/controls/{control_id}?agent_uuid=...&time_range=5m
```

See [docs/REFERENCE.md](../docs/REFERENCE.md) for complete API documentation.

## Development

### Database Migrations

```bash
# Create a new migration
make alembic-revision MESSAGE="description"

# Run migrations
make alembic-upgrade

# Rollback migration
make alembic-downgrade
```

### Running Tests

```bash
# Run all tests
make test

# Run specific test file
uv run pytest tests/test_controls.py

# Run with coverage
uv run pytest --cov=agent_control_server
```

### Code Quality

```bash
# Lint
make lint

# Auto-fix linting issues
make lint-fix

# Type checking
make typecheck
```

### Available Make Commands

From the `server/` directory:

| Command | Description |
|---------|-------------|
| `make run` | Start development server |
| `make test` | Run tests |
| `make lint` | Run ruff linting |
| `make lint-fix` | Auto-fix linting issues |
| `make typecheck` | Run mypy type checking |
| `make alembic-upgrade` | Run database migrations |
| `make alembic-downgrade` | Rollback last migration |
| `make alembic-revision MESSAGE="..."` | Create new migration |

## Production Deployment

### Docker

```bash
# Build image (from repo root)
docker build -f server/Dockerfile -t agent-control-server .

# Run container
docker run -p 8000:8000 \
  -e DB_URL=postgresql://... \
  -e AGENT_CONTROL_API_KEY_ENABLED=true \
  -e AGENT_CONTROL_API_KEYS=your-key-here \
  agent-control-server
```

### Direct Installation

```bash
# Build wheel
cd server
uv build

# Install on target system
pip install dist/agent_control_server-*.whl

# Run with CLI
agent-control-server
```

See [docs/REFERENCE.md](../docs/REFERENCE.md) for complete deployment documentation.
