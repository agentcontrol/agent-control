# Agent Control - Python SDK

Unified Python SDK for Agent Control - providing agent protection, monitoring, and rule enforcement in one clean package.

## Installation

```bash
pip install agent-control-sdk
```

## Quick Start

### Simple Initialization

```python
import agent_control

# Initialize at the base of your agent
agent_control.init(
    agent_name="My Customer Service Bot",
    agent_id="csbot-prod-v1"
)

# Use the control decorator
from agent_control import control

@control()
async def handle_message(message: str):
    return f"Processed: {message}"
```

### With Full Metadata

```python
import agent_control

agent_control.init(
    agent_name="Customer Service Bot",
    agent_id="csbot-prod-v1",
    agent_description="Handles customer inquiries and support",
    agent_version="2.1.0",
    server_url="http://localhost:8000",
    # Add any custom metadata
    team="customer-success",
    environment="production"
)
```

## Features

### 1. Simple Initialization

One line to set up your agent with full protection:

```python
agent_control.init(agent_name="...", agent_id="...")
```

This automatically:
- Creates an Agent instance with your metadata
- Discovers and loads `rules.yaml`
- Registers with the Agent Control server
- Enables the `@control()` decorator

### 2. Decorator-Based Protection

Protect any function with server-defined controls:

```python
@control()
async def process(user_text: str):
    return user_text
```

### 3. HTTP Client

Use the client directly for custom workflows:

```python
from agent_control import AgentControlClient

async with AgentControlClient() as client:
    # Check server health
    health = await client.health_check()
    print(f"Server status: {health['status']}")
    
    # Evaluate a step
    result = await agent_control.evaluation.check_evaluation(
        client,
        agent_uuid="your-agent-uuid",
        step={"type": "llm_inference", "input": "User input here"},
        stage="pre"
    )
```

### 4. Agent Metadata

Access your agent information:

```python
agent = agent_control.current_agent()
print(f"Agent: {agent.agent_name}")
print(f"ID: {agent.agent_id}")
print(f"Version: {agent.agent_version}")
```

## Complete Example

```python
import asyncio
import agent_control
from agent_control import control, ControlViolationError

# Initialize
agent_control.init(
    agent_name="Customer Support Bot",
    agent_id="support-bot-v1",
    agent_version="1.0.0"
)

# Protect with server-defined controls
@control()
async def handle_message(message: str) -> str:
    # Automatically checked against server-side controls
    return f"Processed: {message}"

@control()
async def generate_response(query: str) -> str:
    # Output is automatically evaluated
    return f"Response with SSN: 123-45-6789"

# Use the functions
async def main():
    try:
        # Safe input
        result1 = await handle_message("Hello, I need help")
        print(result1)
        
        # Output with PII (may be blocked by controls)
        result2 = await generate_response("Get user info")
        print(result2)
        
    except ControlViolationError as e:
        print(f"Blocked by control '{e.control_name}': {e.message}")

asyncio.run(main())
```

## API Reference

### Initialization

#### `agent_control.init()`

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

Initialize Agent Control with your agent's information.

**Parameters:**
- `agent_name`: Human-readable name
- `agent_id`: Unique identifier (user-defined)
- `agent_description`: Optional description
- `agent_version`: Optional version string
- `server_url`: Optional server URL (defaults to `AGENT_CONTROL_URL` env var)
- `rules_file`: Optional rules file path (auto-discovered if not provided)
- `**kwargs`: Additional metadata

**Returns:** `Agent` instance

### Decorator

#### `@control()`

```python
def control(policy: Optional[str] = None):
```

Decorator to protect a function with server-defined controls.

**Parameters:**
- `policy`: Optional policy name to use (defaults to agent's assigned policy)

**Example:**
```python
@control()
async def my_func(text: str):
    return text

# Or with specific policy
@control(policy="strict-policy")
async def sensitive_func(data: str):
    return data
```

### Client

#### `AgentControlClient`

```python
class AgentControlClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        timeout: float = 30.0
    ):
```

Async HTTP client for Agent Control server.

**Methods:**

- `health_check()` - Check server health
- Use with module functions like `agent_control.agents.*`, `agent_control.controls.*`, etc.

**Example:**
```python
from agent_control import AgentControlClient
import agent_control

async with AgentControlClient(base_url="http://server") as client:
    health = await client.health_check()
    agent = await agent_control.agents.init_agent(client, agent_data, tools)
```

### Models

If `agent-control-models` is installed, these classes are available:

- `Agent` - Agent metadata
- `ProtectionRequest` - Protection request model
- `ProtectionResult` - Protection result with helper methods
- `HealthResponse` - Health check response

## Configuration

### Environment Variables

- `AGENT_CONTROL_URL` - Server URL (default: `http://localhost:8000`)
- `AGENT_CONTROL_API_KEY` - API key for authentication (optional)

### Server-Defined Controls

Controls are defined on the server via the API or web dashboard, not in code. This keeps security policies centrally managed and allows updating controls without redeploying your application.

See the [Reference Guide](../../docs/REFERENCE.md) for complete control configuration documentation.

## Package Name

This package is named `agent-control-sdk` (with hyphen in PyPI) and imported as `agent_control` (with underscore in Python):

```bash
# Install (uses hyphen)
pip install agent-control-sdk

# Import (uses underscore)
import agent_control
```

Basic usage:

```python
import agent_control
from agent_control import control, ControlViolationError

agent_control.init(agent_name="...", agent_id="...")

@control()
async def handle(message: str):
    return message
```

## SDK Logging

The SDK uses Python's standard `logging` module with loggers under the `agent_control.*` namespace. Following library best practices, the SDK only adds a NullHandler - your application controls where logs go and how they're formatted.

### Configuring SDK Logs in Your Application

**Option 1: Standard Python logging configuration (recommended)**

```python
import logging

# Basic configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# Set agent_control logs to DEBUG
logging.getLogger('agent_control').setLevel(logging.DEBUG)
```

**Option 2: SDK settings (control log categories)**

```python
from agent_control.settings import configure_settings

# Configure which categories of logs the SDK emits
configure_settings(
    log_enabled=True,           # Master switch for all SDK logging
    log_span_start=True,        # Emit span start logs
    log_span_end=True,          # Emit span end logs
    log_control_eval=True,      # Emit control evaluation logs
)
```

### Controlling What the SDK Logs

The SDK provides behavioral settings to control which categories of logs are emitted:

```python
from agent_control.settings import configure_settings

# Disable specific log categories
configure_settings(
    log_control_eval=False,  # Don't emit per-control evaluation logs
    log_span_start=False,    # Don't emit span start logs
)
```

These behavioral settings work independently of log levels:
- **Behavioral settings**: Control which categories of logs the SDK emits
- **Log levels**: Control which logs are displayed (via Python's logging module)

### Environment Variables

Configure SDK logging via environment variables:

```bash
# Behavioral settings (what to log)
export AGENT_CONTROL_LOG_ENABLED=true
export AGENT_CONTROL_LOG_SPAN_START=true
export AGENT_CONTROL_LOG_SPAN_END=true
export AGENT_CONTROL_LOG_CONTROL_EVAL=true
```

### Using SDK Loggers in Your Code

If you're extending the SDK or want consistent logging:

```python
from agent_control import get_logger

# Creates logger under agent_control namespace
logger = get_logger(__name__)

logger.info("Processing started")
logger.debug("Detailed debug info")
```

**Default Settings:**
- `log_enabled`: `true`
- All behavioral settings: `enabled`

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

See the examples directory for complete examples:

- [Customer Support Agent](../../examples/customer_support_agent/) - Full example with multiple tools
- [LangChain SQL Agent](../../examples/langchain/) - SQL injection protection
- [Galileo Luna-2 Integration](../../examples/galileo/) - AI-powered toxicity detection

## Documentation

- [Reference Guide](../../docs/REFERENCE.md) - Complete API and configuration reference
- [Examples Overview](../../examples/README.md) - Working code examples and patterns
- [Architecture](./ARCHITECTURE.md) - SDK architecture and design patterns

## License

Apache License 2.0 - see LICENSE file for details.
