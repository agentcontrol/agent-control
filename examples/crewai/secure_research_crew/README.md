# Secure Research Crew -- CrewAI Multi-Agent with Per-Agent Policies

A production-quality example of a 3-agent CrewAI crew where each agent has its own Agent Control policy with distinct controls.

## What It Demonstrates

- **Per-agent policies**: Different controls for different agent roles, all assigned to a single runtime agent and differentiated by `step_names` in control scopes.
- **Multiple evaluator types**: SQL, LIST, JSON, JSON Schema, and REGEX evaluators working together.
- **Deny and steer actions**: Hard blocks for security violations, corrective steering for recoverable issues.
- **Idempotent setup**: The setup script handles 409 conflicts gracefully and can be run repeatedly.

## Architecture

```
                          Agent Control Server
                    +---------------------------------+
                    |  data-access-policy             |
                    |    researcher-sql-safety  [deny] |
                    |    researcher-restricted  [deny] |
                    |                                  |
                    |  analysis-validation-policy      |
                    |    analyst-required-fields [deny] |
                    |    analyst-methodology     [steer]|
                    |                                  |
                    |  content-safety-policy           |
                    |    writer-pii-blocker     [deny] |
                    +---------------------------------+
                                  |
                     @control() decorator
                                  |
    +------------------------------------------------------------+
    |                   CrewAI Sequential Crew                   |
    |                                                            |
    |  +--------------+   +--------------+   +---------------+  |
    |  |  Researcher  |-->|   Analyst    |-->|    Writer     |  |
    |  |              |   |              |   |               |  |
    |  | query_database|  | validate_data|   | write_report  |  |
    |  | (step_name)  |   | (step_name)  |   | (step_name)   |  |
    |  +--------------+   +--------------+   +---------------+  |
    +------------------------------------------------------------+
```

Each tool's `step_name` matches the `step_names` in its corresponding control scope, so the SQL evaluator only fires for `query_database`, the JSON evaluator only fires for `validate_data`, etc.

## Scenarios

| # | Scenario | Agent | Control | Evaluator | Action | Expected |
|---|----------|-------|---------|-----------|--------|----------|
| 1 | Happy path | All | All | All | observe | Report generated |
| 2 | SQL injection | Researcher | researcher-sql-safety | SQL | deny | Query blocked |
| 3 | Restricted table | Researcher | researcher-restricted-tables | LIST | deny | Query blocked |
| 4 | Missing methodology | Analyst | analyst-methodology-check | JSON Schema | steer | Auto-corrected, then passes |
| 5 | PII in report | Writer | writer-pii-blocker | REGEX | deny | Report blocked |

## Prerequisites

- **Python 3.12+**
- **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Docker** for PostgreSQL (required by Agent Control server)
- **Agent Control server** running (`make server-run` from monorepo root)

## Running

### 1. Install dependencies

From the monorepo root:

```bash
make sync
```

Then from this directory:

```bash
cd examples/crewai/secure_research_crew
uv pip install -e . --upgrade
```

### 2. Start the Agent Control server

In a separate terminal from the monorepo root:

```bash
make server-run
```

### 3. Create controls and policies (one-time, idempotent)

```bash
uv run --active python setup_controls.py
```

### 4. Run the demo

```bash
uv run --active python -m secure_research_crew.main
```

Scenarios 1-5 run with direct tool calls (no LLM needed). The optional full crew run at the end requires `OPENAI_API_KEY`.

## How It Works

### Single Agent, Multiple Policies

The SDK only supports one `agent_control.init()` call per process, so all three CrewAI agents share a single Agent Control agent identity (`secure-research-crew`). Each policy's controls target specific `step_names`:

- `query_database` -- matched by controls in `data-access-policy`
- `validate_data` -- matched by controls in `analysis-validation-policy`
- `write_report` -- matched by controls in `content-safety-policy`

### Steering Retry Pattern

When a steer control fires (e.g., missing methodology), the tool catches the `ControlSteerError`, parses the structured JSON steering context, applies corrections, and retries up to 3 times:

```python
except ControlSteerError as e:
    guidance = json.loads(e.steering_context)
    for key, hint in guidance.get("retry_with", {}).items():
        current_request[key] = "auto-generated value"
    continue  # retry
```

### Direct Tool Testing

Scenarios 2-5 call tools directly (bypassing CrewAI's LLM orchestration) to demonstrate control behavior without incurring API costs. The full crew run is optional and exercises the same controls through CrewAI's agent loop.
