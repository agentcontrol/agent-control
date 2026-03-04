# CrewAI Customer Support with Agent Control + Guardrails

Combines Agent Control (security/compliance) with CrewAI Guardrails (quality retries) for production customer support.

## What It Does
Agent Control (Security): PRE/POST/FINAL blocks unauthorized access and PII.
CrewAI Guardrails (Quality): validates length/structure/tone with up to 3 retries.

## Prerequisites

Before running this example, ensure you have:

- **Python 3.12+**
- **uv** — Fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Docker** — For running PostgreSQL (required by Agent Control server)

## Installation

### 1. Install Monorepo Dependencies

From the monorepo root, install all workspace packages:

```bash
cd /path/to/agent-control
make sync
```

This installs the Agent Control SDK and all workspace packages in editable mode.

### 2. Install CrewAI Example Dependencies

Navigate to the CrewAI example and install its specific dependencies:

```bash
cd examples/crewai
uv pip install -e . --upgrade
```


### 3. Set OpenAI API Key

Create a `.env` file or export the environment variable:

```bash
export OPENAI_API_KEY="your-key-here"
```

### 4. Start the Agent Control Server

In a separate terminal, start the server from the monorepo root:

```bash
cd /path/to/agent-control
make server-run
```

**Verify server is running:**
```bash
curl http://localhost:8000/health
```

### 5. Setup Content Controls (One-Time)

From the `examples/crewai` directory, run the setup script:

```bash
uv run python setup_content_controls.py
```


## Running the Example

Make sure you're in the `examples/crewai` directory and run:

```bash
uv run python content_agent_protection.py
```

### Expected Behavior

| Scenario | Layer | Result |
|----------|-------|--------|
| Unauthorized access | Agent Control PRE | Blocked |
| PII in tool output | Agent Control POST | Blocked |
| Short/low-quality response | Guardrails | Retry then pass |
| Agent bypass attempt | Agent Control FINAL | Blocked |

### Output Legend
PRE checks input before the LLM.
POST checks tool output for PII.
FINAL checks the crew’s final response.
Agent Control blocks immediately (no retries), violations are logged.
Guardrails retry with feedback (quality-only).

## Agent Control + CrewAI Integration

Agent Control works seamlessly **with** CrewAI's agent orchestration:

1. **CrewAI Agent Layer**: Plans tasks, selects tools, manages conversation flow
2. **Agent Control Layer**: Enforces controls and business rules at tool boundaries

```
User Request
    ↓
CrewAI Agent (planning & orchestration)
    ↓
Decides to call tool
    ↓
@control() decorator (PRE-execution)  ← LAYER 1: Validates input
    ↓
Tool executes (LLM generation)
    ↓
@control() decorator (POST-execution)  ← LAYER 2: Validates tool output
    ↓
If blocked, agent may generate own response
    ↓
Final Output Validation  ← LAYER 3: Validates crew output (catches bypass)
    ↓
Return to user (or block if control violated)
```


