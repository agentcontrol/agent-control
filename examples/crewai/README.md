# CrewAI + Agent Control Examples

Combines **Agent Control** (runtime security & compliance) with **CrewAI** (agent orchestration) for production-grade AI agents.

**Agent Control** enforces guardrails at tool boundaries -- blocking unauthorized access, PII leakage, SQL injection, and more -- while **CrewAI Guardrails** handle quality retries. Both coexist without code changes to CrewAI.

## How It Works

```
User Request
    |
    v
CrewAI Agent (planning & orchestration)
    |
    v
@control() decorator (PRE check)     <- LAYER 1: Agent Control validates input
    |
    v
Tool executes (LLM call, DB query, etc.)
    |
    v
@control() decorator (POST check)    <- LAYER 2: Agent Control validates output
    |
    v
CrewAI Guardrails (quality retries)  <- LAYER 3: CrewAI validates quality
    |
    v
Return to user (or block / steer / warn)
```

**Agent Control** blocks or steers immediately (security). **CrewAI Guardrails** retry with feedback (quality). Controls are defined on the **server** -- update rules without redeploying agents.

## Prerequisites

- **Python 3.12+**
- **uv** -- Fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Docker** -- For PostgreSQL (`docker compose -f docker-compose.dev.yml up -d`)
- **OpenAI API key** -- `export OPENAI_API_KEY="your-key"` (only needed for full LLM crew runs; simulated scenarios work without it)

## Quick Start

### 1. Install dependencies

From the monorepo root:

```bash
cd /path/to/agent-control
make sync
```

### 2. Start the Agent Control server

In a separate terminal:

```bash
make server-run
```

Verify it's running:

```bash
curl http://localhost:8000/health
# {"status":"healthy","version":"0.1.0"}
```

### 3. Pick an example and run it

Each example has a `setup_controls.py` (one-time, idempotent) and a main script:

```bash
cd examples/crewai/secure_research_crew
uv run --active python setup_controls.py
uv run --active python -m secure_research_crew.main
```

---

## Examples

### 1. [Steering Financial Agent](./steering_financial_agent/) -- Deny, Steer & Warn

Demonstrates all three Agent Control action types in a wire-transfer scenario:

| Action | Behavior | Example |
|--------|----------|---------|
| **DENY** | Hard block, no recovery | Sanctioned country, fraud detected |
| **STEER** | Pause, guide agent to correct, retry | 2FA required, manager approval needed |
| **WARN** | Log for audit, no blocking | New recipient, unusual activity |

```bash
cd examples/crewai/steering_financial_agent
uv run --active python setup_controls.py
uv run --active python -m steering_financial_agent.main
```

### 2. [Evaluator Showcase](./evaluator_showcase/) -- All 4 Built-in Evaluators

Demonstrates every built-in evaluator in a data-analyst scenario:

| Evaluator | Stage | Purpose |
|-----------|-------|---------|
| **SQL** | PRE | Block DROP/DELETE, enforce LIMIT, prevent injection |
| **LIST** | PRE | Restrict access to sensitive tables |
| **REGEX** | POST | Catch SSN, email, credit cards in query results |
| **JSON** | PRE | Validate required fields, enforce constraints, steer for missing data |

```bash
cd examples/crewai/evaluator_showcase
uv run --active python setup_controls.py
uv run --active python -m evaluator_showcase.main
```

### 3. [Secure Research Crew](./secure_research_crew/) -- Multi-Agent Crew with Per-Role Policies

A production-quality **3-agent sequential crew** (Researcher, Analyst, Writer) where each agent has its own policy with distinct controls. This is the pattern you'd use in real multi-agent systems.

```
+--------------+     +--------------+     +---------------+
|  Researcher  | --> |   Analyst    | --> |    Writer     |
|              |     |              |     |               |
| query_database|    | validate_data|     | write_report  |
+--------------+     +--------------+     +---------------+
       |                    |                     |
 data-access-policy   analysis-validation   content-safety
  - SQL safety [deny]  - Required fields [deny] - PII blocker [deny]
  - Restricted tables  - Methodology [steer]
    [deny]
```

**5 scenarios** -- all run without LLM calls (direct tool testing):

| # | Scenario | Agent | Evaluator | Action | Result |
|---|----------|-------|-----------|--------|--------|
| 1 | Happy path | All 3 | All | allow | Report generated with sources |
| 2 | SQL injection | Researcher | SQL | deny | "Multiple SQL statements not allowed" |
| 3 | Restricted table | Researcher | LIST | deny | salary_data access blocked |
| 4 | Missing methodology | Analyst | JSON Schema | steer | Auto-corrected, passes on retry |
| 5 | PII in report | Writer | REGEX | deny | SSN/email/phone blocked |

```bash
cd examples/crewai/secure_research_crew
uv run --active python setup_controls.py
uv run --active python -m secure_research_crew.main
```

### 4. [Content Publishing Flow](./content_publishing_flow/) -- CrewAI Flow with Routing & Human-in-the-Loop

A complete **CrewAI Flow** using `@start`, `@listen`, and `@router` decorators with Agent Control guardrails at every pipeline stage. Content is routed through different paths based on risk level, with embedded crews and steering for human approval.

```
@start: intake_request (JSON validation)
    |
@listen: research (Researcher + Fact-Checker)
    |
@listen: draft_content (PII + banned topic checks)
    |
@router: quality_gate
    |
    +-- "low_risk" (blog_post)      --> auto_publish (final PII scan)
    +-- "high_risk" (press_release) --> compliance_review (legal + editor steering)
    +-- "escalation" (internal_memo)--> human_review (STEER: manager approval)
```

**6 scenarios** covering all three routing paths plus control blocking:

| # | Scenario | Flow Path | Result |
|---|----------|-----------|--------|
| 1 | Blog post | low_risk -> auto-publish | Published |
| 2 | Press release | high_risk -> compliance review | Steered (exec summary), then published |
| 3 | Internal memo | escalation -> human review | Steered: pending manager approval |
| 4 | Invalid request | intake blocked | JSON evaluator: missing fields |
| 5 | Banned topic | draft blocked | LIST evaluator: "insider trading" detected |
| 6 | PII in draft | draft blocked | REGEX evaluator: email/SSN/phone detected |

```bash
cd examples/crewai/content_publishing_flow
uv run --active python setup_controls.py
uv run --active python -m content_publishing_flow.main
```

---

## Feature Coverage

| Feature | Ex 1 | Ex 2 | Ex 3 | Ex 4 |
|---------|:----:|:----:|:----:|:----:|
| `@control()` decorator | Yes | Yes | Yes | Yes |
| PRE-execution checks | Yes | Yes | Yes | Yes |
| POST-execution checks | Yes | Yes | Yes | Yes |
| **deny** action | Yes | Yes | Yes | Yes |
| **steer** action | Yes | Yes | Yes | Yes |
| **warn** action | Yes | | | |
| Regex evaluator | | Yes | Yes | Yes |
| List evaluator | Yes | Yes | Yes | Yes |
| JSON evaluator | Yes | Yes | Yes | Yes |
| SQL evaluator | | Yes | Yes | |
| Steering context + retry loop | Yes | Yes | Yes | Yes |
| ControlViolationError handling | Yes | Yes | Yes | Yes |
| ControlSteerError handling | Yes | Yes | Yes | Yes |
| **Multi-agent crew** | | | **Yes** | |
| **Per-agent policies** | | | **Yes** | |
| **CrewAI Flow (@start/@listen/@router)** | | | | **Yes** |
| **Conditional routing** | | | | **Yes** |
| **Human-in-the-loop (steer)** | | | | **Yes** |
| **Pydantic state management** | | | | **Yes** |

## Architecture Deep Dive

### Multi-Agent Crew (Example 3)

The SDK supports one `agent_control.init()` per process. All three CrewAI agents share a single Agent Control identity, but each tool's `step_name` routes it to the right policy:

```
                     Single agent_control.init()
                              |
    +------------------------------------------------------------+
    |                   CrewAI Sequential Crew                    |
    |                                                             |
    |  +--------------+   +--------------+   +----------------+  |
    |  |  Researcher  |-->|   Analyst    |-->|    Writer      |  |
    |  | query_database|  | validate_data|   | write_report   |  |
    |  +--------------+   +--------------+   +----------------+  |
    +------------------------------------------------------------+
           |                     |                    |
    data-access-policy   analysis-validation   content-safety
     (SQL + LIST deny)    (JSON deny + steer)   (REGEX deny)
```

### CrewAI Flow (Example 4)

```
@start: intake_request -----> @listen: research -----> @listen: draft_content
   (JSON validation)        (LIST + REGEX checks)     (REGEX + LIST checks)
                                                              |
                                                    @router: quality_gate
                                                       /      |       \
                                                      /       |        \
                                           "low_risk"   "high_risk"  "escalation"
                                               |            |             |
                                          auto_publish  compliance    human_review
                                          (REGEX PII)   (JSON + STEER) (STEER)
```
