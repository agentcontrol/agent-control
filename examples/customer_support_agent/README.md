# Customer Support Agent Example

This example demonstrates how to integrate the `agent-control` SDK into an existing application. It simulates a **Customer Support Agent** - a realistic enterprise scenario that shows the key patterns for protecting AI agents with server-defined controls.

## Why This Example?

- **Universally understood use case**: Customer support is familiar to everyone
- **Natural need for guardrails**: PII protection, prompt injection defense
- **Multiple operation types**: LLM calls + tool calls (database, knowledge base, tickets)
- **Enterprise-relevant**: Shows patterns real companies would use

## Quick Start

```bash
# 1. Install SDK and evaluators (first time only)
pip install -e sdks/python -e evaluators

# 2. Start all services (database, server, UI, demo controls)
./examples/customer_support_agent/demo.sh start

# 3. Run the demo
python examples/customer_support_agent/run_demo.py
```

The `demo.sh start` command:
- Starts PostgreSQL database
- Runs migrations
- Starts the API server (http://localhost:8000)
- Starts the UI (http://localhost:4000)
- **Registers the agent with demo controls** (PII detection, prompt injection)

When you open the UI, you'll see the agent with controls already configured.

### Other Commands

```bash
# Check status of all services
./examples/customer_support_agent/demo.sh status

# Stop all services
./examples/customer_support_agent/demo.sh stop

# Reset everything (deletes database, asks for confirmation)
./examples/customer_support_agent/demo.sh reset
```

## Prerequisites

### First-Time Setup

1. **Install the SDK and evaluators**:
   ```bash
   pip install -e sdks/python
   pip install -e evaluators
   ```

2. **Install UI dependencies**:
   ```bash
   cd ui
   pnpm install
   ```

### Manual Setup (alternative to demo.sh)

If you prefer to run services manually:

1. **Start the database** (requires Docker):
   ```bash
   cd server
   docker compose up -d
   ```

2. **Run database migrations**:
   ```bash
   cd server
   make alembic-upgrade
   ```

3. **Start the server** (Terminal 1):
   ```bash
   cd server
   make run
   ```
   Server runs at http://localhost:8000

4. **Start the UI** (Terminal 2):
   ```bash
   cd ui
   pnpm dev
   ```
   UI runs at http://localhost:4000

## Running the Demo

After `demo.sh start`, the agent already has demo controls configured. Just run:

```bash
python examples/customer_support_agent/run_demo.py
```

Test different scenarios:
```
You: Hello, I need help with a refund
Agent: I understand you'd like a refund. Let me look into your order...

You: /test-pii
Running PII Detection Tests...
(Messages with SSN patterns will be blocked)

You: /test-injection
Running Prompt Injection Tests...
(Injection attempts will be blocked)

You: /quit
Goodbye!
```

### Automated Mode

Run all test scenarios automatically:
```bash
python examples/customer_support_agent/run_demo.py --automated
```

### Reset Agent Controls

To remove all controls from the agent (keeps the agent registered):
```bash
python examples/customer_support_agent/run_demo.py --reset
```

### Adding Custom Controls

1. Open http://localhost:4000
2. Click on "Customer Support Agent" in the list
3. Click "Add Control" to create additional controls

See [Example Controls](#example-controls-to-configure) below for configuration examples.

## Available Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/test-safe` | Run safe message tests |
| `/test-pii` | Test PII detection (if control configured) |
| `/test-injection` | Test prompt injection detection |
| `/lookup <query>` | Look up customer (e.g., `/lookup C001`) |
| `/search <query>` | Search knowledge base |
| `/ticket` | Create a test support ticket |
| `/quit` | Exit the demo |

## Key Concepts

### 1. SDK Initialization

Initialize once at application startup:

```python
import agent_control

agent_control.init(
    agent_name="customer-support-agent",
    agent_description="AI-powered customer support assistant",
)
```

This:
- Registers the agent with the server
- Fetches controls associated with the agent
- Enables the `@control()` decorator

### 2. Protecting Functions

Use the `@control()` decorator on any function you want to protect:

```python
from agent_control import control

@control()
async def respond_to_customer(message: str) -> str:
    response = await llm.generate(message)
    return response
```

The decorator:
- Calls the server with `check_stage="pre"` before execution (validates input)
- Calls the server with `check_stage="post"` after execution (validates output)
- Raises `ControlViolationError` if a control triggers with "deny" action

### 3. Handling Violations

Catch `ControlViolationError` to provide graceful fallbacks:

```python
from agent_control import ControlViolationError

try:
    response = await respond_to_customer(user_message)
except ControlViolationError as e:
    # Control triggered - return safe fallback
    print(f"Blocked by: {e.control_name}")
    response = "I cannot help with that request."
```

### 4. Controls are Server-Side

**Important**: Controls are defined on the server via the UI, not in code.

This design provides:
- **Centralized management**: Security team controls safeguards without code changes
- **Instant updates**: Change controls without redeploying agents
- **Audit trail**: Server logs all control evaluations
- **Separation of concerns**: Developers focus on features, security team on safeguards

## Project Structure

```
customer_support_agent/
├── README.md                 # This file
├── demo.sh                   # Start/stop/reset script
├── setup_demo_controls.py    # Creates agent and demo controls
├── support_agent.py          # Main agent with SDK integration
└── run_demo.py               # Interactive demo runner
```

### demo.sh

Manages the full demo lifecycle:
- `start` - Starts database, server, UI, and sets up demo controls
- `stop` - Stops all services
- `reset` - Deletes database and stops services
- `status` - Shows service status

### setup_demo_controls.py

Creates the demo agent with pre-configured controls:
- `block-ssn-in-output` - Blocks responses containing SSN patterns
- `block-prompt-injection` - Blocks common injection attempts
- `block-credit-card` - Blocks credit card numbers in input

### support_agent.py

Contains:
- SDK initialization
- Mock services (LLM, database, knowledge base, tickets)
- Protected functions with `@control()` decorator
- `CustomerSupportAgent` class with error handling

### run_demo.py

Contains:
- Interactive chat loop
- Test command handlers (`/test-pii`, `/test-injection`, etc.)
- Automated test scenarios

## Example Controls to Configure

The demo setup creates three controls automatically. Here are examples of additional controls you might add:

### PII Detection (Post-check on output)
```yaml
name: block-pii-in-output
scope:
  step_types: ["llm"]
  stages: ["post"]
selector:
  path: output
evaluator:
  name: regex
  config:
    pattern: '\d{3}-\d{2}-\d{4}'  # SSN pattern
action:
  decision: deny
  message: "Response contains PII (SSN pattern)"
```

### Prompt Injection (Pre-check on input)
```yaml
name: block-prompt-injection
scope:
  step_types: ["llm"]
  stages: ["pre"]
selector:
  path: input
evaluator:
  name: regex
  config:
    pattern: '(?i)(ignore.*instructions|system:|you are now)'
action:
  decision: deny
  message: "Potential prompt injection detected"
```

### Toxic Content (Pre-check on input)
```yaml
name: block-toxic-input
scope:
  step_types: ["llm"]
  stages: ["pre"]
selector:
  path: input
evaluator:
  name: galileo.luna2
  config:
    stage_type: local
    metric: input_toxicity
    operator: gt
    target_value: 0.8
action:
  decision: deny
  message: "Inappropriate content detected"
```

## Testing the Integration

1. **Without controls**: Run the demo without configuring any controls. All messages should pass through.

2. **With PII control**: Add a PII detection control, then run `/test-pii`. Messages with SSN patterns should be blocked.

3. **With injection control**: Add a prompt injection control, then run `/test-injection`. Injection attempts should be blocked.

## Next Steps

- Explore the [main examples](../) for more integration patterns
- Read the [SDK documentation](../../sdks/python/README.md)
- Check the [server API documentation](../../server/README.md)
