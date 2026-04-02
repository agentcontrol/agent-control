# CrewAI Financial Agent with Steering Controls

Demonstrates Agent Control actions in a realistic wire-transfer scenario using CrewAI.

## Action Types

| Action | Behavior | Example |
|--------|----------|---------|
| **DENY** | Hard block, agent cannot recover | Sanctioned country, fraud detected |
| **STEER** | Pause execution, guide agent to correct and retry | 2FA required, manager approval needed |
| **OBSERVE** | Record for audit, agent continues uninterrupted | New recipient, unusual activity |

The key difference: **DENY** raises `ControlViolationError` (permanent), **STEER** raises `ControlSteerError` (recoverable), and **OBSERVE** records a non-blocking advisory event.

## Scenarios

| # | Scenario | Amount | Controls Triggered | Outcome |
|---|----------|--------|--------------------|---------|
| 1 | Small transfer to new vendor | $2,500 | observe (new recipient) | ALLOWED + audit trail |
| 2 | Transfer to North Korea | $500 | deny (sanctioned country) | BLOCKED |
| 3 | Large transfer | $15,000 | steer (2FA required) | STEERED -> verified -> ALLOWED |
| 4 | Very large transfer | $75,000 | steer (2FA + manager) | STEERED -> approved -> ALLOWED |
| 5 | High fraud score | $3,000 | deny (fraud > 0.8) | BLOCKED |

## Controls Created

- `deny-sanctioned-countries` — LIST evaluator, blocks OFAC countries
- `deny-high-fraud-score` — JSON evaluator, blocks fraud_score > 0.8
- `steer-require-2fa` — JSON evaluator with oneOf schema, steers for 2FA
- `steer-require-manager-approval` — JSON evaluator, steers for approval
- `observe-new-recipient` — LIST evaluator, records unknown recipients
- `observe-pii-in-confirmation` — REGEX evaluator, records PII in output

## Prerequisites

- Python 3.12+
- Agent Control server running (`make server-run` from repo root)
- OpenAI API key

## Running

```bash
# From repo root — install dependencies
make sync

# Navigate to example
cd examples/crewai/steering_financial_agent

# Install example dependencies
uv pip install -e . --upgrade

# Set your OpenAI key
export OPENAI_API_KEY="your-key"

# Set up controls (one-time)
uv run --active python setup_controls.py

# Run the demo
uv run --active python -m steering_financial_agent.main
```

## How Steering Works

When Agent Control returns a **steer** action, the SDK raises `ControlSteerError` with a `steering_context` containing JSON guidance:

```json
{
  "required_actions": ["verify_2fa"],
  "reason": "Transfers >= $10,000 require identity verification.",
  "retry_with": {"verified_2fa": true}
}
```

The agent catches this error, performs the required actions (verify 2FA, get approval, etc.), then retries the same operation with the corrected parameters. This is the key pattern:

```python
try:
    result = await protected_function(amount=15000, verified_2fa=False)
except ControlSteerError as e:
    guidance = json.loads(e.steering_context)
    # Perform required actions...
    result = await protected_function(amount=15000, verified_2fa=True)  # Retry
```
