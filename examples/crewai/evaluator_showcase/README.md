# CrewAI Data Analyst - Evaluator Showcase

Demonstrates all four built-in Agent Control evaluators in a realistic data-analyst scenario using CrewAI.

## Evaluators

| Evaluator | Stage | Purpose | Example |
|-----------|-------|---------|---------|
| **SQL** | PRE | Validate query structure and safety | Block DROP, enforce LIMIT |
| **LIST** | PRE | Access control via allowlists/blocklists | Restrict sensitive tables |
| **REGEX** | POST | Pattern detection in free-text output | Catch SSN, email, credit cards |
| **JSON** | PRE | Schema validation with constraints | Require fields, enforce ranges |

## Scenarios

### SQL Evaluator
| # | Query | Outcome |
|---|-------|---------|
| 1a | `SELECT ... FROM orders LIMIT 10` | ALLOWED |
| 1b | `DROP TABLE orders; SELECT ...` | DENIED (blocked operation + multi-statement) |
| 1c | `SELECT * FROM orders` | DENIED (missing required LIMIT) |
| 1d | `DELETE FROM orders WHERE ...` | DENIED (blocked operation) |

### LIST Evaluator
| # | Table | Outcome |
|---|-------|---------|
| 2a | `orders` | ALLOWED (not restricted) |
| 2b | `salary_data` | DENIED (restricted table) |
| 2c | `audit_log` | DENIED (restricted table) |

### REGEX Evaluator
| # | Results Contain | Outcome |
|---|-----------------|---------|
| 3a | Order data (no PII) | ALLOWED |
| 3b | SSN `123-45-6789` + email | DENIED (PII detected post-execution) |

### JSON Evaluator
| # | Request | Outcome |
|---|---------|---------|
| 4a | All fields valid | ALLOWED |
| 4b | Missing `date_range` | DENIED (required field) |
| 4c | `max_rows: 50000` | DENIED (exceeds max of 10000) |
| 4d | Missing `purpose` | STEERED (auto-filled, then allowed) |

## Controls Created

- `sql-safety-check` — SQL evaluator: block destructive ops, enforce LIMIT
- `restrict-sensitive-tables` — LIST evaluator: block salary_data, audit_log, etc.
- `pii-in-query-results` — REGEX evaluator: detect SSN/email/credit cards in output
- `validate-analysis-request` — JSON evaluator: require dataset + date_range, constrain max_rows
- `steer-require-purpose` — JSON evaluator with STEER: collect analysis purpose for audit

## Prerequisites

- Python 3.12+
- Agent Control server running (`make server-run` from repo root)
- OpenAI API key (only needed for JSON and CrewAI crew scenarios)

## Running

```bash
# From repo root — install dependencies
make sync

# Navigate to example
cd examples/crewai/evaluator_showcase

# Install example dependencies
uv pip install -e . --upgrade

# Set your OpenAI key (optional for SQL/LIST/REGEX scenarios)
export OPENAI_API_KEY="your-key"

# Set up controls (one-time)
uv run --active python setup_controls.py

# Run the demo
uv run --active python -m evaluator_showcase.main
```

## Key Insight

Each evaluator serves a different purpose at a different stage:

```
  Request arrives
       |
       v
  ┌─────────────────────┐
  │  SQL Evaluator (PRE) │  Is this query structurally safe?
  └──────────┬──────────┘
             v
  ┌──────────────────────┐
  │ LIST Evaluator (PRE)  │  Is the target table allowed?
  └──────────┬───────────┘
             v
  ┌──────────────────────┐
  │ JSON Evaluator (PRE)  │  Are required fields present and valid?
  └──────────┬───────────┘
             v
      Query Executes
             |
             v
  ┌───────────────────────┐
  │ REGEX Evaluator (POST) │  Do results contain PII patterns?
  └───────────┬───────────┘
              v
       Return Results
```
