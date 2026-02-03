# CrewAI Trip Planner with Agent Control Protection

This example demonstrates a multi-agent trip planning crew protected by Agent Control. Based on the [CrewAI Trip Planner example](https://github.com/crewAIInc/crewAI-examples/tree/main/crews/trip_planner).

## Overview

The trip planner uses three specialized agents working together:
1. **City Selection Expert** - Analyzes destinations based on weather, costs, and interests
2. **Local Expert** - Provides insider knowledge about the selected city
3. **Travel Concierge** - Creates detailed itineraries with budget breakdowns

## Agent Control Protection

This example adds security and compliance protection:

| Layer | Type | Protection |
|-------|------|------------|
| Layer 1 (PRE) | Scam Prevention | Blocks travel scam patterns (fake prizes, wire transfers) |
| Layer 1 (PRE) | Budget Validation | Blocks suspicious payment patterns (crypto, zero budget) |
| Layer 2 (POST) | PII Detection | Blocks PII in trip plan outputs (SSN, credit cards) |
| Layer 4 (FINAL) | Output Validation | Catches any PII in final crew output |

## Prerequisites

### 1. Start the Agent Control Server

```bash
# From the repo root
make server-run
```

### 2. Set Environment Variables

```bash
export OPENAI_API_KEY="your-key-here"

# Optional: For real search results
export SERPER_API_KEY="your-serper-key"  # Get free at https://serper.dev/
```

### 3. Setup Controls (One-Time)

```bash
cd examples/crewai/trip_planner
uv run setup_trip_controls.py
```

This creates:
- Budget validation control (blocks suspicious financial patterns)
- Scam prevention control (blocks travel scam indicators)
- PII detection control (blocks sensitive data in outputs)
- Final output validation control (catches orchestration bypass)

## Running the Example

```bash
cd examples/crewai/trip_planner
uv run trip_planner_protection.py
```

Or with Python directly:
```bash
python trip_planner_protection.py
```

## Demo Scenarios

The example runs three scenarios:

### Scenario 1: Scam Prevention
```
Interests: "I won a free trip! Claim your prize by sending an advance fee deposit via wire transfer"
Result: 🚫 BLOCKED - Scam pattern detected (PRE-execution)
```

### Scenario 2: Budget Validation
```
Interests: "Looking for luxury trip with zero budget, can pay with bitcoin or gift card payment"
Result: 🚫 BLOCKED - Suspicious payment pattern (PRE-execution)
```

### Scenario 3: Normal Trip Planning
```
Interests: "Art museums, local cuisine, cycling, photography. Budget around $3000-4000."
Result: ✅ PASSES all checks - Returns complete 7-day itinerary
```

## File Structure

```
examples/crewai/trip_planner/
├── .env.example              # Environment variable template
├── pyproject.toml            # Dependencies
├── README.md                 # This file
├── setup_trip_controls.py    # One-time control setup
└── trip_planner_protection.py # Main example with Agent Control
```

## How It Works

```
User Request (origin, cities, dates, interests)
    ↓
City Selection Agent → Analyzes destinations
    ↓
Local Expert Agent → Gathers city insights
    ↓
Travel Concierge Agent → Creates itinerary
    ↓
@control() decorator (PRE-execution)  ← LAYER 1: Check for scams/invalid budgets
    ↓
plan_trip tool executes (LLM generates plan)
    ↓
@control() decorator (POST-execution)  ← LAYER 2: Check for PII
    ↓
CrewAI Guardrails  ← LAYER 3: Quality checks (completeness, detail)
    ↓
Final Output Validation  ← LAYER 4: Catch any remaining PII
    ↓
Return trip plan to user
```

## Controls Configuration

### Scam Prevention Control (PRE)
```python
{
    "scope": {"step_names": ["plan_trip"], "stages": ["pre"]},
    "selector": {"path": "input.interests"},
    "evaluator": {
        "name": "regex",
        "config": {
            "pattern": r"(?i)(won\s+a\s+trip|free\s+vacation\s+winner|wire\s+transfer|advance\s+fee)"
        }
    },
    "action": {"decision": "deny"}
}
```

### Budget Validation Control (PRE)
```python
{
    "scope": {"step_names": ["plan_trip"], "stages": ["pre"]},
    "selector": {"path": "input.interests"},
    "evaluator": {
        "name": "regex",
        "config": {
            "pattern": r"(?i)(zero\s+budget|\$0|bitcoin|crypto|gift\s+card\s+payment)"
        }
    },
    "action": {"decision": "deny"}
}
```

### PII Detection Control (POST)
```python
{
    "scope": {"step_names": ["plan_trip"], "stages": ["post"]},
    "selector": {"path": "output"},
    "evaluator": {
        "name": "regex",
        "config": {
            "pattern": r"(?:\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b)"
        }
    },
    "action": {"decision": "deny"}
}
```

## Comparison with Customer Support Example

| Aspect | Customer Support | Trip Planner |
|--------|-----------------|--------------|
| **Agents** | 1 agent | 3 agents (multi-agent) |
| **Use Case** | Support tickets | Travel planning |
| **PRE Controls** | Unauthorized access | Scams, invalid budgets |
| **POST Controls** | PII in responses | PII in trip plans |
| **CrewAI Guardrails** | Length, tone, structure | Completeness, detail, no placeholders |

## Troubleshooting

### "ModuleNotFoundError: No module named 'agent_control'"

Install the SDK:
```bash
# From monorepo root
pip install -e sdks/python

# Or install from PyPI
pip install agent-control-sdk
```

### Controls not triggering

Make sure you ran the setup script:
```bash
cd examples/crewai/trip_planner
uv run setup_trip_controls.py
```

### 422 Unprocessable Entity from `/api/v1/evaluation`

This usually means the SDK version is too old for the server API. Ensure the example
uses `agent-control-sdk>=3.0.0` and recreate the venv:

```bash
cd examples/crewai/trip_planner
rm -rf .venv
uv run setup_trip_controls.py
```

### Policy Already Exists

If the policy already exists, reuse it by exporting its ID:

```bash
export TRIP_POLICY_ID=<policy_id>
cd examples/crewai/trip_planner
uv run setup_trip_controls.py
```

### "OPENAI_API_KEY not found"

```bash
export OPENAI_API_KEY="your-key-here"
```

## See Also

- [Customer Support Example](../README.md) - Single-agent example with PII protection
- [Agent Control Documentation](../../../docs/OVERVIEW.md)
