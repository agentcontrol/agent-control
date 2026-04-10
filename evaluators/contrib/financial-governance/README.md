# Financial Governance Evaluators for Agent Control

Evaluators that enforce financial spend limits and transaction policies for autonomous AI agents.

As agents transact autonomously via protocols like [x402](https://github.com/coinbase/x402) and payment layers like [agentpay-mcp](https://github.com/AI-Agent-Economy/agentpay-mcp), enterprises need governance over what agents spend. These evaluators bring financial policy enforcement into the Agent Control framework.

## Evaluators

### `financial_governance.spend_limit`

Tracks cumulative agent spend and enforces rolling budget limits. Stateful — records approved transactions and checks new ones against accumulated spend.

- **Per-transaction cap** — reject any single payment above a threshold (`BudgetLimit` with no window)
- **Rolling period budget** — reject payments that would exceed a time-windowed budget (`BudgetWindow(kind="rolling", ...)`)
- **Calendar-aligned budget** — reject payments that exceed a day/week/month budget (`BudgetWindow(kind="fixed", ...)`)
- **Scoped budgets** — per-dimension or composite counters via `scope_by`
- **Pluggable storage** — abstract `SpendStore` protocol with built-in `InMemorySpendStore`; bring your own PostgreSQL, Redis, etc.
- **Atomic enforcement** — `check_and_record()` prevents TOCTOU races in single-process deployments

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

# Or install through the builtin package extra
pip install "agent-control-evaluators[financial-governance]"
```

## Configuration

### Spend Limit

The `spend_limit` evaluator is configured via a list of `BudgetLimit` objects. Each limit is evaluated independently — the first violation wins.

```yaml
controls:
  - name: spend-limit
    evaluator:
      type: financial_governance.spend_limit
      config:
        limits:
          # Per-transaction cap: single payment ≤ 100 USDC
          - amount: "100.00"
            currency: USDC
          # Per-channel rolling 24h budget: each channel limited to 1000 USDC/day
          - amount: "1000.00"
            currency: USDC
            scope_by: [channel]
            window:
              kind: rolling
              seconds: 86400
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
        min_amount: "0.01"
        max_amount: "5000.00"
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
    "amount": "50.00",             # required — Decimal or numeric string
    "currency": "USDC",            # required — payment currency
    "recipient": "0xABC...",       # required — payment recipient
    # optional context fields (used for scope_by)
    "channel": "slack",
    "agent_id": "agent-42",
    "session_id": "sess-1",
}
```

> **Note:** Use `Decimal` or string representations for `amount` — never raw `float`. Floating-point arithmetic is imprecise for money. The evaluator internally converts to `Decimal`.

## BudgetLimit Model

```python
from decimal import Decimal
from agent_control_evaluator_financial_governance.spend_limit import (
    BudgetLimit, BudgetWindow, SpendLimitConfig, SpendLimitEvaluator,
)

# Per-transaction cap (no window)
cap = BudgetLimit(amount=Decimal("100"), currency="USDC")

# Rolling 24-hour budget, scoped per channel
rolling = BudgetLimit(
    amount=Decimal("1000"),
    currency="USDC",
    scope_by=("channel",),
    window=BudgetWindow(kind="rolling", seconds=86400),
)

# Calendar-day budget (UTC by default)
daily = BudgetLimit(
    amount=Decimal("500"),
    currency="USDC",
    window=BudgetWindow(kind="fixed", unit="day"),
)

# Calendar-day budget aligned to New York local midnight
ny_daily = BudgetLimit(
    amount=Decimal("500"),
    currency="USDC",
    window=BudgetWindow(kind="fixed", unit="day", timezone="America/New_York"),
)

config = SpendLimitConfig(limits=[cap, rolling, daily])
evaluator = SpendLimitEvaluator(config)
```

### BudgetWindow

| kind | Required fields | Notes |
|------|----------------|-------|
| `"rolling"` | `seconds` | Sliding window from `now - seconds` |
| `"fixed"` | `unit` (`"day"`, `"week"`, or `"month"`), optional `timezone` | Calendar-aligned in the configured IANA timezone, UTC by default |

### scope_by semantics

`scope_by` lists the context dimension keys to isolate spend buckets.

- `scope_by=()` (default) — global budget: all spend in that currency shares one counter
- `scope_by=("channel",)` — one counter per unique `channel` value
- `scope_by=("agent_id",)` — one counter per unique `agent_id`
- `scope_by=("channel", "agent_id")` — one counter per unique `(channel, agent_id)` **composite** pair

Spend in `channel-A` does **not** count against `channel-B`'s budget.

**Strict tuple matching (v0.1.1):** ALL dimensions in `scope_by` must be present
in the transaction data for a limit to apply. A transaction carrying only
`channel` will NOT match a limit scoped to `("channel", "agent_id")` — the
missing `agent_id` dimension means this limit is skipped entirely for that
transaction. This prevents unintentional scope widening where a partially
populated context inherits a broader budget than intended.

## Context-Aware Limits

Context fields (`channel`, `agent_id`, `session_id`) can be provided in two ways:

**Option A: Via `step.context`** (recommended for engine integration)

```python
step = Step(
    type="tool",
    name="payment",
    input={"amount": "75.00", "currency": "USDC", "recipient": "0xABC"},
    context={
        "channel": "experimental",
        "agent_id": "agent-42",
    },
)
```

When using `selector.path: "*"`, the evaluator merges `step.context` fields into the transaction data automatically. Fields already present in `step.input` are never overwritten by context.

**Option B: Inline in the transaction dict** (simpler, for direct SDK use)

```python
result = await evaluator.evaluate({
    "amount": "75.00",
    "currency": "USDC",
    "recipient": "0xABC",
    "channel": "experimental",
    "agent_id": "agent-42",
})
```

## Custom SpendStore

The `SpendStore` protocol requires four methods for full evaluator compatibility:
- `record_spend()`
- `get_spend()`
- `check_and_record()`
- `check_and_record_many()`

Implement them for your backend:

```python
from decimal import Decimal
from agent_control_evaluator_financial_governance.spend_limit import (
    SpendStore, SpendLimitConfig, SpendLimitEvaluator,
)

class PostgresSpendStore:
    """Example: PostgreSQL-backed spend tracking."""

    def __init__(self, connection_string: str):
        self._conn = connect(connection_string)

    def record_spend(
        self,
        amount: Decimal,
        currency: str,
        metadata: dict | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO agent_spend (amount, currency, metadata, recorded_at)"
            " VALUES (%s, %s, %s, NOW())",
            (str(amount), currency, json.dumps(metadata)),
        )

    def get_spend(
        self,
        currency: str,
        start: float,
        end: float | None = None,
        scope: dict[str, str] | None = None,
    ) -> Decimal:
        # Build WHERE clause for scope filtering
        clauses = [
            "currency = %s",
            "recorded_at >= to_timestamp(%s)",
        ]
        params = [currency, start]
        if end is not None:
            clauses.append("recorded_at <= to_timestamp(%s)")
            params.append(end)
        if scope:
            for k, v in scope.items():
                clauses.append(f"metadata->>{k!r} = %s")
                params.append(v)
        where = " AND ".join(clauses)
        row = self._conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) FROM agent_spend WHERE {where}",
            params,
        ).fetchone()
        return Decimal(str(row[0]))

    def check_and_record(
        self,
        amount: Decimal,
        currency: str,
        limit: Decimal,
        start: float,
        end: float | None = None,
        scope: dict[str, str] | None = None,
        metadata: dict | None = None,
    ) -> tuple[bool, Decimal]:
        # Use a DB transaction for atomicity
        with self._conn.transaction():
            current = self.get_spend(currency, start, end, scope)
            if current + amount > limit:
                return False, current
            self.record_spend(amount, currency, metadata)
            return True, current

    def check_and_record_many(
        self,
        amount: Decimal,
        currency: str,
        checks: list[BudgetCheck],
        metadata: dict | None = None,
    ) -> tuple[bool, int | None, list[Decimal]]:
        with self._conn.transaction():
            current_spends: list[Decimal] = []
            for idx, check in enumerate(checks):
                current = self.get_spend(currency, check.start, check.end, check.scope)
                current_spends.append(current)
                if current + amount > check.limit:
                    return False, idx, current_spends
            self.record_spend(amount, currency, metadata)
            return True, None, current_spends

# Use it:
store = PostgresSpendStore("postgresql://...")
evaluator = SpendLimitEvaluator(config, store=store)
```

> **Single-process atomicity note:** `InMemorySpendStore.check_and_record()` and `check_and_record_many()` use a `threading.Lock` to atomically validate and record within a single process. For multi-process or distributed deployments, your custom store must implement true database-level atomics (e.g., PostgreSQL `SELECT ... FOR UPDATE`, Redis Lua scripts).

## Running Tests

```bash
cd evaluators/contrib/financial-governance
pip install -e ".[dev]"
pytest tests/ -v
```

## Design Decisions

1. **Decimal for money** — All monetary amounts use `Decimal`, never `float`. Floating-point arithmetic is unsuitable for financial calculations.
2. **BudgetLimit + BudgetWindow models** — Expressive, composable budget definitions that replace the previous flat config. Each limit is independent; first violation wins.
3. **Strict tuple scope matching** — `scope_by=("channel",)` creates a separate counter for each channel value. A limit scoped to `("channel", "agent_id")` only applies to transactions that carry BOTH dimensions. Missing dimensions cause the limit to be skipped, not widened.
4. **Atomic check_and_record()** — Eliminates the TOCTOU race of separate `get_spend()` + `record_spend()` calls. Single-process safe with `threading.Lock`; production stores should use DB-level atomics.
5. **InMemorySpendStore retention** — Default retention is 31 days (covers the longest calendar month). Previous 7-day default caused undercounting for `fixed month` budgets after day 8. Production deployments with monthly windows should use a persistent store.
6. **Decoupled from data source** — The `SpendStore` protocol means no new tables in core Agent Control. Bring your own persistence.
6. **Fail-open on malformed input** — Missing or malformed data returns `matched=False, error=None`, following Agent Control conventions. The `error` field is reserved for evaluator crashes, not policy decisions.

## Related Projects

- [x402](https://github.com/coinbase/x402) — HTTP 402 payment protocol
- [agentpay-mcp](https://github.com/up2itnow0822/agentpay-mcp) — MCP server for non-custodial agent payments

## License

Apache-2.0 — see [LICENSE](../../../LICENSE).
