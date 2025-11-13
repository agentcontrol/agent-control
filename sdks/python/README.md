# Agent Protect - Python SDK

Unified Python SDK for Agent Protect - providing agent protection, monitoring, and rule enforcement in one clean package.

## Installation

```bash
pip install agent-protect
```

## Quick Start

### Simple Initialization

```python
import agent_protect

# Initialize at the base of your agent
agent_protect.init(
    agent_name="My Customer Service Bot",
    agent_id="csbot-prod-v1"
)

# Use the protect decorator
from agent_protect import protect

@protect('input-validation', input='message')
async def handle_message(message: str):
    return f"Processed: {message}"
```

### With Full Metadata

```python
import agent_protect

agent_protect.init(
    agent_name="Customer Service Bot",
    agent_id="csbot-prod-v1",
    agent_description="Handles customer inquiries and support",
    agent_version="2.1.0",
    server_url="https://protect.example.com",
    # Add any custom metadata
    team="customer-success",
    environment="production"
)
```

## Features

### 1. Simple Initialization

One line to set up your agent with full protection:

```python
agent_protect.init(agent_name="...", agent_id="...")
```

This automatically:
- Creates an Agent instance with your metadata
- Discovers and loads `rules.yaml`
- Registers with the Agent Protect server
- Enables the `@protect` decorator

### 2. Decorator-Based Protection

Protect any function with YAML-defined rules:

```python
@protect('input-check', input='user_text')
async def process(user_text: str):
    return user_text
```

### 3. HTTP Client

Use the client directly for custom workflows:

```python
async with agent_protect.AgentProtectClient() as client:
    # Check content safety
    result = await client.check_protection(
        content="User input here",
        context={"user_id": "123"}
    )
    
    if result.is_safe:
        print("Safe to process!")
    
    # Check server health
    health = await client.health_check()
    print(f"Server status: {health['status']}")
```

### 4. Agent Metadata

Access your agent information:

```python
agent = agent_protect.get_agent()
print(f"Agent: {agent.agent_name}")
print(f"ID: {agent.agent_id}")
print(f"Version: {agent.agent_version}")
```

## Complete Example

```python
import asyncio
import agent_protect
from agent_protect import protect

# Initialize
agent_protect.init(
    agent_name="Customer Support Bot",
    agent_id="support-bot-v1",
    agent_version="1.0.0"
)

# Protect input
@protect('input-validation', input='message', context='ctx')
async def handle_message(message: str, ctx: dict):
    # Input is automatically checked against rules.yaml
    return f"Processed: {message}"

# Protect output
@protect('output-filter', output='response')
async def generate_response(query: str) -> str:
    # Output is automatically filtered (e.g., PII redaction)
    return f"Response with SSN: 123-45-6789"

# Use the functions
async def main():
    try:
        # Safe input
        result1 = await handle_message(
            "Hello, I need help",
            {"user_id": "123"}
        )
        print(result1)
        
        # Output with PII (will be redacted)
        result2 = await generate_response("Get user info")
        print(result2)  # SSN will be [REDACTED]
        
    except Exception as e:
        print(f"Blocked: {e}")

asyncio.run(main())
```

## API Reference

### Initialization

#### `agent_protect.init()`

```python
def init(
    agent_name: str,
    agent_id: str,
    agent_description: Optional[str] = None,
    agent_version: Optional[str] = None,
    server_url: Optional[str] = None,
    rules_file: Optional[str] = None,
    **kwargs
) -> Agent:
```

Initialize Agent Protect with your agent's information.

**Parameters:**
- `agent_name`: Human-readable name
- `agent_id`: Unique identifier (user-defined)
- `agent_description`: Optional description
- `agent_version`: Optional version string
- `server_url`: Optional server URL (defaults to `AGENT_PROTECT_URL` env var)
- `rules_file`: Optional rules file path (auto-discovered if not provided)
- `**kwargs`: Additional metadata

**Returns:** `Agent` instance

### Decorator

#### `@protect()`

```python
def protect(step_id: str, **data_sources):
```

Decorator to protect a function with rules from `rules.yaml`.

**Parameters:**
- `step_id`: Step identifier matching rules.yaml
- `**data_sources`: Mapping of data types to parameter names

**Example:**
```python
@protect('input-check', input='text', context='ctx')
async def my_func(text: str, ctx: dict):
    return text
```

### Client

#### `AgentProtectClient`

```python
class AgentProtectClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0
    ):
```

Async HTTP client for Agent Protect server.

**Methods:**

- `health_check()` - Check server health
- `check_protection(content, context=None)` - Check content safety
- `register_agent(agent)` - Register an agent

**Example:**
```python
async with AgentProtectClient(base_url="http://server") as client:
    result = await client.check_protection("content")
```

### Models

If `agent-protect-models` is installed, these classes are available:

- `Agent` - Agent metadata
- `ProtectionRequest` - Protection request model
- `ProtectionResult` - Protection result with helper methods
- `HealthResponse` - Health check response

## Configuration

### Environment Variables

- `AGENT_PROTECT_URL` - Server URL (default: `http://localhost:8000`)
- `AGENT_ID` - Agent identifier (optional)

### Rules File

Create a `rules.yaml` in your project:

```yaml
input-validation:
  step_id: "input-check"
  description: "Validate user inputs"
  rules:
    - match:
        string: ["forbidden", "blocked"]
      action: deny
      data: input
  default_action: allow
```

See the [Rules Guide](../../examples/langgraph/my_agent/RULES_GUIDE.md) for complete documentation.

## Package Name

This package is named `agent-protect` (with hyphen in PyPI) but imported as `agent_protect` (with underscore in Python):

```bash
# Install (uses hyphen)
pip install agent-protect

# Import (uses underscore)
import agent_protect
```

Or use the simpler decorator approach:

```python
import agent_protect

agent_protect.init(agent_name="...", agent_id="...")

from agent_protect import protect

@protect('input-check', input='message')
async def handle(message: str):
    return message
```

## Development

```bash
# Install in development mode
cd sdks/python
uv sync

# Run tests
uv run pytest

# Lint
uv run ruff check .
```

## Examples

See the [examples directory](../../examples/langgraph/my_agent/) for complete examples:

- `example_with_agent_protect.py` - Using `agent_protect.init()`
- `simple_example.py` - Minimal example
- `agent_with_rules.py` - LangGraph integration

## Documentation

- [Quick Start](../../examples/langgraph/my_agent/QUICK_START.md)
- [Rules Guide](../../examples/langgraph/my_agent/RULES_GUIDE.md)
- [Decorator Explained](../../examples/langgraph/my_agent/DECORATOR_EXPLAINED.md)
- [How Data Flows](../../examples/langgraph/my_agent/HOW_DATA_FLOWS.md)

## License

Apache License 2.0 - see LICENSE file for details.
