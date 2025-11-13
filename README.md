# Agent Protect

A modular agent protection system with isolated server and SDK components, built with `uv` and modern Python best practices.

## Architecture

This project uses a **multi-workspace structure** with separate workspaces for SDK and server:

```
agent-protect/
├── models/          # 📦 Shared Pydantic models (foundation)
├── server/          # 🚀 FastAPI server workspace (API provider)
│   └── pyproject.toml  # Independent workspace
└── sdks/            # 🔧 SDKs workspace
    ├── pyproject.toml  # Independent workspace
    └── python/         # Python SDK implementation
```

### Workspace Benefits

- ✅ **Independent development**: SDK and server teams can work independently
- ✅ **Separate dependency management**: Each workspace manages its own dependencies
- ✅ **Isolated testing**: Run tests in each workspace without interference
- ✅ **Type safety**: Shared models guarantee consistency via path references

### Package Relationships

```
models (v0.1.0)
    ↓ (path reference)
    ├── server (v0.1.0) - references ../models
    └── sdks/python (v0.1.0) - references ../../models
```

## Common Patterns from Popular Python Packages

This project follows patterns used by leading Python packages:

| Pattern | Example Packages | Our Implementation |
|---------|-----------------|-------------------|
| **Shared Models** | `google-api-core`, `stripe` | `agent-protect-models` |
| **Pydantic + JSON** | `anthropic-sdk`, `openai` | `BaseModel` with `to_dict()`/`from_json()` |
| **Workspace Monorepo** | `ansible`, `pytest` | `uv` workspace with three packages |
| **Async Client** | `httpx`, `aiohttp` | Async `AgentProtectClient` |
| **SDK with Models** | `boto3/botocore`, `google-cloud-*` | SDK imports from models package |

## Quick Start

### Installation

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/yourusername/agent-protect.git
cd agent-protect
```

### Working with Workspaces

Each workspace is independent. Navigate to the workspace directory and use `uv` commands:

**For the Server:**
```bash
cd server
uv sync  # Install dependencies
uv run agent-protect-server

# Or with auto-reload for development
uv run uvicorn agent_protect_server.main:app --reload
```

Server will be available at `http://localhost:8000`

**For the SDK:**
```bash
cd sdks
uv sync  # Install dependencies
uv run pytest  # Run tests
```

### Using the SDK

```python
import asyncio
from agent_protect import AgentProtectClient

async def main():
    async with AgentProtectClient() as client:
        # Check server health
        health = await client.health_check()
        print(f"Server: {health}")
        
        # Analyze content
        result = await client.check_protection(
            content="Is this safe?",
            context={"source": "user_input"}
        )
        
        # Use the result
        if result:  # Boolean check
            print("✓ Content is safe")
        
        if result.is_confident(threshold=0.9):
            print(f"✓ High confidence: {result.confidence}")
        
        print(result)  # Human-readable output

asyncio.run(main())
```

## Package Details

### 📦 agent-protect-models

**Purpose**: Shared Pydantic models for type-safe communication

**Key Features**:
- Pydantic v2 models with full validation
- JSON serialization/deserialization (`to_json()`, `from_json()`)
- Dictionary conversion (`to_dict()`, `from_dict()`)
- Forward compatibility (ignores unknown fields)
- Rich type hints

**Models**:
- `HealthResponse`: Server health status
- `ProtectionRequest`: Request for content analysis
- `ProtectionResponse`: Server analysis result
- `ProtectionResult`: Client-side result with convenience methods

[📖 Full documentation](models/README.md)

### 🚀 agent-protect-server

**Purpose**: FastAPI server providing agent protection API

**Key Features**:
- FastAPI with automatic OpenAPI docs
- Async/await support
- Environment-based configuration
- Health check endpoint
- Protection analysis endpoint

**Endpoints**:
- `GET /health` - Health check
- `POST /protect` - Analyze content for safety

[📖 Full documentation](server/README.md)

### 🔧 agent-protect

**Purpose**: Unified Python SDK for agent protection, monitoring, and rule enforcement

**Key Features**:
- Simple initialization with `agent_protect.init()`
- `@protect` decorator for rule enforcement
- Async HTTP client for server communication
- Type-safe with Pydantic models
- Auto-discovery of rules and configuration
- Agent registration and metadata tracking

**Usage**:
```python
import agent_protect

# Initialize once
agent_protect.init(agent_name="My Bot", agent_id="bot-v1")

# Use decorator
from agent_protect import protect

@protect('input-check', input='message')
async def handle(message: str):
    return message

# Or use client directly
async with agent_protect.AgentProtectClient() as client:
    result = await client.check_protection("test content")
```

[📖 Full documentation](sdks/python/README.md)

## Shared Models Pattern

### Why Shared Models?

Popular packages use shared models to ensure consistency:

- **boto3/botocore**: Separate `botocore` package with all AWS service models
- **Google APIs**: `google-api-core` provides common types
- **Stripe**: Models package used by both CLI and SDK
- **Anthropic/OpenAI**: SDK includes models matching API schema

### Pydantic + JSON Pattern

Our `BaseModel` provides both Pydantic validation and JSON compatibility:

```python
from agent_protect_models import ProtectionRequest

# Create with validation
request = ProtectionRequest(content="Hello")

# Serialize to JSON
json_str = request.to_json()
# '{"content":"Hello"}'

# Deserialize from JSON  
request2 = ProtectionRequest.from_json(json_str)

# Dictionary conversion
data = request.to_dict()
request3 = ProtectionRequest.from_dict(data)
```

This pattern is used by:
- **Anthropic SDK**: `.model_dump()`, `.model_validate()`
- **OpenAI SDK**: Similar Pydantic-based models
- **FastAPI**: Native Pydantic support

### Example: Adding a New Endpoint

1. **Define models** (in `models/`):

```python
# models/src/agent_protect_models/scan.py
from .base import BaseModel

class ScanRequest(BaseModel):
    url: str
    deep_scan: bool = False

class ScanResult(BaseModel):
    is_safe: bool
    threats_found: list[str]
```

2. **Use in server** (in `server/`):

```python
# server/src/agent_protect_server/main.py
from agent_protect_models import ScanRequest, ScanResult

@app.post("/scan", response_model=ScanResult)
async def scan_url(request: ScanRequest) -> ScanResult:
    # Implementation
    return ScanResult(is_safe=True, threats_found=[])
```

3. **Use in SDK** (in `sdk/`):

```python
# sdks/python/src/agent_protect/__init__.py
from agent_protect_models import ProtectionRequest, ProtectionResult

async def scan_url(self, url: str, deep: bool = False) -> ScanResult:
    request = ScanRequest(url=url, deep_scan=deep)
    response = await self._client.post(
        f"{self.base_url}/scan",
        json=request.to_dict()
    )
    return ScanResult.from_dict(response.json())
```

## Development

### Project Structure

```
agent-protect/
├── pyproject.toml          # Root configuration (linting, type checking)
├── README.md               # This file
├── DEPLOYMENT.md           # Deployment guide
├── models/
│   ├── pyproject.toml      # Models package config
│   ├── README.md           # Models documentation
│   └── src/
│       └── agent_protect_models/
│           ├── __init__.py
│           ├── base.py     # Base model with utilities
│           ├── health.py   # Health models
│           └── protection.py # Protection models
├── server/
│   ├── pyproject.toml      # Server workspace config
│   ├── README.md           # Server documentation
│   └── src/
│       └── agent_protect_server/
│           ├── __init__.py
│           ├── main.py     # FastAPI application
│           └── config.py   # Configuration
└── sdks/
    ├── pyproject.toml      # SDKs workspace config
    ├── README.md           # SDKs documentation
    └── python/
        ├── pyproject.toml  # Python SDK package config
        ├── README.md       # Python SDK documentation
        └── src/
            └── agent_protect/
                └── __init__.py  # Unified SDK: client, init, protect decorator
```

### Running Tests

```bash
# Test server workspace
cd server && uv run pytest

# Test SDK workspace
cd sdks && uv run pytest

# Test models separately (if needed)
cd models && uv run pytest
```

### Linting and Type Checking

Each workspace has its own linting and type checking:

```bash
# Server workspace
cd server
uv run ruff check .
uv run mypy src

# SDK workspace
cd sdks
uv run ruff check .
uv run mypy python/src
```

### Building Packages

```bash
# Build server
cd server && uv build

# Build SDK
cd sdks/python && uv build

# Build models
cd models && uv build

# Wheels will be in each package's dist/ directory
```

## Deployment

All three packages can be deployed independently:

### 1. Deploy Models (First)

```bash
cd models
uv build
uv publish  # or upload to private PyPI
```

### 2. Deploy Server

```bash
# Docker
docker build -t agent-protect-server:latest -f server/Dockerfile .
docker run -p 8000:8000 agent-protect-server:latest

# Or cloud platform (AWS, GCP, Azure)
# See DEPLOYMENT.md for details
```

### 3. Deploy SDK

```bash
cd sdk
uv build
uv publish  # or distribute wheels
```

Users install with:
```bash
pip install agent-protect-sdk
```

[📖 Full deployment guide](DEPLOYMENT.md)

## Configuration

### Server Configuration

Create `.env` in `server/`:

```env
HOST=0.0.0.0
PORT=8000
DEBUG=false
API_VERSION=v1
```

### SDK Configuration

Configure in code:

```python
client = AgentProtectClient(
    base_url="https://api.yourcompany.com",
    timeout=60.0
)
```

## API Documentation

When the server is running, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Examples

### Example 1: Simple Content Check

```python
import asyncio
from agent_protect import AgentProtectClient

async def check_content(text: str):
    async with AgentProtectClient() as client:
        result = await client.check_protection(text)
        return result.is_safe

# Use it
is_safe = asyncio.run(check_content("Hello, world!"))
print(f"Is safe: {is_safe}")
```

### Example 2: Batch Processing

```python
import asyncio
from agent_protect import AgentProtectClient

async def check_batch(texts: list[str]):
    async with AgentProtectClient() as client:
        tasks = [
            client.check_protection(text)
            for text in texts
        ]
        results = await asyncio.gather(*tasks)
        return results

texts = ["text1", "text2", "text3"]
results = asyncio.run(check_batch(texts))
for text, result in zip(texts, results):
    print(f"{text}: {result}")
```

### Example 3: With Context

```python
import asyncio
from agent_protect import AgentProtectClient

async def check_with_context():
    async with AgentProtectClient() as client:
        result = await client.check_protection(
            content="User message here",
            context={
                "source": "chat",
                "user_id": "12345",
                "session": "abc"
            }
        )
        
        if result.is_confident(threshold=0.95):
            print(f"High confidence result: {result}")
        else:
            print(f"Low confidence, manual review needed: {result}")

asyncio.run(check_with_context())
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## License

Apache License 2.0 - see LICENSE file for details

## Support

- 📖 Documentation: See individual package READMEs
- 🐛 Issues: GitHub Issues
- 💬 Discussions: GitHub Discussions

## Roadmap

- [ ] Add authentication/API keys
- [ ] Implement caching layer
- [ ] Add more protection algorithms
- [ ] Rate limiting
- [ ] Metrics and monitoring
- [ ] Async batch processing
- [ ] Webhook support
- [ ] CLI tool
