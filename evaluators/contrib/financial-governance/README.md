# Financial Governance Evaluators for Agent Control

Evaluators that enforce financial spend limits and transaction policies for autonomous AI agents.

As agents transact autonomously via protocols like [x402](https://github.com/coinbase/x402) and payment layers like [agentpay-mcp](https://github.com/AI-Agent-Economy/agentpay-mcp), enterprises need governance over what agents spend. These evaluators bring financial policy enforcement into the Agent Control framework.

## Evaluators

### `financial_governance.spend_limit`

Tracks cumulative agent spend and enforces rolling budget limits. Stateful — records approved transactions and checks new ones against accumulated spend.

- **Per-transaction cap** — reject any single payment above a threshold
- **Rolling period budget** — reject payments that would exceed a time-windowed budget
- **Context-aware overrides** — different limits per channel, agent, or session via evaluate metadata
- **Pluggable storage** — abstract `SpendStore` protocol with built-in `InMemorySpendStore`; bring your own PostgreSQL, Redis, etc.

### `financial_governance.transaction_policy`

Static policy checks with no state tracking. Enforces structural rules on individual transactions.

- **Currency allowlist** — only permit specific currencies (e.g., `["USDC", "USDT"]`)
- **Recipient blocklist/allowlist** — control which addresses an agent can pay
- **Amount bounds** — minimum and maximum per-transaction limits

## Installation

```bash
# From the repo root (development)
cd evaluators/contrib/financial-governance
pip install -e ".[dev]"
```

## Configuration

### Spend Limit

```yaml
controls:
  - name: spend-limit
    evaluator:
      type: financial_governance.spend_limit
      config:
        max_per_transaction: 100.0    # Max USDC per single payment
        max_per_period: 1000.0        # Rolling 24h budget
        period_seconds: 86400         # Budget window (default: 24 hours)
        currency: USDC                # Currency to govern
    selector:
      path: input                     # Extract step.input (transaction dict)
    action: deny
```

### Transaction Policy

```yaml
controls:
  - name: transaction-policy
    evaluator:
      type: financial_governance.transaction_policy
      config:
        allowed_currencies: [USDC, USDT]
        blocked_recipients: ["0xDEAD..."]
        allowed_recipients: ["0xALICE...", "0xBOB..."]
        min_amount: 0.01
        max_amount: 5000.0
    selector:
      path: input
    action: deny
```

## Selector Paths

Both evaluators support two selector configurations:

- **`selector.path: "input"`** (recommended) — The evaluator receives `step.input` directly, which should be the transaction dict.
- **`selector.path: "*"`** — The evaluator receives the full Step object. It automatically extracts `step.input` for transaction fields and `step.context` for channel/agent/session metadata.

## Input Data Schema

The transaction dict (from `step.input`) should contain:

```python
# step.input — transaction payload
{
    "amount": 50.0,              # required — transaction amount
    "currency": "USDC",          # required — payment currency
    "recipient": "0xABC...",     # required — payment recipient
}
```

## Context-Aware Limits

Context fields (`channel`, `agent_id`, `session_id`) and per-context limit overrides can be provided in two ways:

**Option A: Via `step.context`** (recommended for engine integration)

```python
step = Step(
    type="tool",
    name="payment",
    input={"amount": 75.0, "currency": "USDC", "recipient": "0xABC"},
    context={
        "channel": "experimental",
        "agent_id": "agent-42",
        "channel_max_per_transaction": 50.0,
        "channel_max_per_period": 200.0,
    },
)
```

When using `selector.path: "*"`, the evaluator merges `step.context` fields into the transaction data automatically. When using `selector.path: "input"`, context fields must be included directly in `step.input`.

**Option B: Inline in the transaction dict** (simpler, for direct SDK use)

```python
result = await evaluator.evaluate({
    "amount": 75.0,
    "currency": "USDC",
    "recipient": "0xABC",
    "channel": "experimental",
    "channel_max_per_transaction": 50.0,
    "channel_max_per_period": 200.0,
})
```

Spend budgets are **scoped by context** — spend in channel A does not count against channel B's budget. When no context fields are present, budgets are global.

## Custom SpendStore

The `SpendStore` protocol requires two methods. Implement them for your backend:

```python
from agent_control_evaluator_financial_governance.spend_limit import (
    SpendStore,
    SpendLimitConfig,
    SpendLimitEvaluator,
)

class PostgresSpendStore:
    """Example: PostgreSQL-backed spend tracking."""

    def __init__(self, connection_string: str):
        self._conn = connect(connection_string)

    def record_spend(self, amount: float, currency: str, metadata: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO agent_spend (amount, currency, metadata, recorded_at) VALUES (%s, %s, %s, NOW())",
            (amount, currency, json.dumps(metadata)),
        )

    def get_spend(self, currency: str, since_timestamp: float) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM agent_spend WHERE currency = %s AND recorded_at >= to_timestamp(%s)",
            (currency, since_timestamp),
        ).fetchone()
        return float(row[0])

# Use it:
store = PostgresSpendStore("postgresql://...")
evaluator = SpendLimitEvaluator(config, store=store)
```

## Running Tests

```bash
cd evaluators/contrib/financial-governance
pip install -e ".[dev]"
pytest tests/ -v
```

## Design Decisions

1. **Decoupled from data source** — The `SpendStore` protocol means no new tables in core Agent Control. Bring your own persistence.
2. **Context-aware limits** — Override keys in the evaluate data dict allow per-channel, per-agent, or per-session limits without multiple evaluator instances.
3. **Python SDK compatible** — Uses the standard evaluator interface; works with both the server and the Python SDK evaluation engine.
4. **Fail-open on errors** — Missing or malformed data returns `matched=False` with an `error` field, following Agent Control conventions.

## Related Projects

- [x402](https://github.com/coinbase/x402) — HTTP 402 payment protocol
- [agentpay-mcp](https://github.com/up2itnow0822/agentpay-mcp) — MCP server for non-custodial agent payments

## License

Apache-2.0 — see [LICENSE](../../../LICENSE).
