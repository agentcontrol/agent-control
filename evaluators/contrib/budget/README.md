# agent-control-evaluator-budget

Budget evaluator for agent-control that tracks cumulative LLM token and cost usage per scope and time window.

## Install

```bash
pip install agent-control-evaluator-budget
```

## Quickstart

```python
from agent_control_evaluator_budget.budget import (
    BudgetEvaluatorConfig,
    BudgetLimitRule,
    ModelPricing,
)

config = BudgetEvaluatorConfig(
    budget_id="support-daily",
    limits=[
        BudgetLimitRule(
            scope={"agent": "support"},
            group_by="user_id",
            window_seconds=86_400,
            limit=500,
            limit_unit="usd_cents",
        ),
        BudgetLimitRule(
            scope={"agent": "support"},
            group_by="user_id",
            window_seconds=86_400,
            limit=50_000,
            limit_unit="tokens",
        ),
    ],
    pricing={
        "gpt-4.1-mini": ModelPricing(input_per_1k=0.04, output_per_1k=0.16),
    },
    model_path="model",
    metadata_paths={
        "agent": "metadata.agent",
        "user_id": "metadata.user_id",
    },
    unknown_model_behavior="block",
)
```

The evaluator reads token usage from standard fields such as `usage.input_tokens` and `usage.output_tokens`. Configure `token_path` only when your event shape uses a custom location.

## Scope and group_by

Each `BudgetLimitRule` has a static `scope` and an optional `group_by` field.

`scope` filters which events a rule applies to. A rule with `scope={"agent": "support"}` only applies when extracted metadata contains `agent="support"`. An empty scope is global.

`group_by` creates independent buckets per extracted metadata value. The common per-user pattern is:

```python
BudgetLimitRule(
    scope={"agent": "support"},
    group_by="user_id",
    window_seconds=86_400,
    limit=500,
    limit_unit="usd_cents",
)
```

With `metadata_paths={"user_id": "metadata.user_id"}`, each user gets a separate daily budget inside the support scope.

## Budget pools

`budget_id` identifies the accumulated budget pool.

Evaluators with the same `budget_id` share accumulated spend and token totals across all evaluator instances. Each evaluator still evaluates using its own configured rules -- the shared state is the bucket (the rolling sum), not the rule set. Evaluators with different `budget_id` values are fully isolated.

Use stable names such as `support-daily`, `billing-global`, or `tenant-acme-monthly`. Avoid generating a new `budget_id` per request unless each request should have an isolated budget.

## Pricing

`ModelPricing` stores cost rates in cents per 1K tokens:

```python
ModelPricing(input_per_1k=0.04, output_per_1k=0.16)
```

`input_per_1k` is applied to input tokens. `output_per_1k` is applied to output tokens.

Pricing is required when any rule uses `limit_unit="usd_cents"`. Token-only rules can omit pricing. If an event uses a model that is not in the pricing table and a cost rule exists, `unknown_model_behavior="block"` fails closed. Use `"warn"` to log a warning and treat the cost as 0.

## Dual Ceiling Pattern

Use two evaluators when cost and token ceilings need independent control records or different `budget_id` pools:

```python
cost_config = BudgetEvaluatorConfig(
    budget_id="support-cost-daily",
    limits=[
        BudgetLimitRule(
            scope={"agent": "support"},
            group_by="user_id",
            window_seconds=86_400,
            limit=500,
            limit_unit="usd_cents",
        )
    ],
    pricing={
        "gpt-4.1-mini": ModelPricing(input_per_1k=0.04, output_per_1k=0.16),
    },
    model_path="model",
    metadata_paths={"agent": "metadata.agent", "user_id": "metadata.user_id"},
)

token_config = BudgetEvaluatorConfig(
    budget_id="support-token-daily",
    limits=[
        BudgetLimitRule(
            scope={"agent": "support"},
            group_by="user_id",
            window_seconds=86_400,
            limit=50_000,
            limit_unit="tokens",
        )
    ],
    metadata_paths={"agent": "metadata.agent", "user_id": "metadata.user_id"},
)
```

This pattern lets cost and token budgets reset, alert, and roll out independently. A single evaluator can also contain both rules when one shared pool and one control result are sufficient.

## Limitations

`InMemoryBudgetStore` is single-process only. State is lost on restart and is not shared across workers or pods.

Use a distributed store for production deployments that run multiple processes, multiple workers, or multiple pods.
