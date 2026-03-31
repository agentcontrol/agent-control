# Agent Control Evaluators

Evaluators analyze agent inputs, outputs, and context to determine if controls should trigger. They provide the core logic for policy enforcement.

## What Evaluators Do

When a control is evaluated:
1. Selector extracts data (e.g., `input.query`, `output.email`)
2. Evaluator analyzes the data against configured rules
3. Returns match/no-match decision
4. Control action is applied if matched (deny, warn, steer, log)

## Built-in Evaluators

### Regex
Pattern matching for text (PII, keywords, SQL injection)
```python
{"name": "regex", "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}}
```

### List
Match against value lists (blocked users, restricted cities, allowed prefixes).
Supports `match_mode: "exact"` for full-string membership, `match_mode: "contains"`
for keyword-style matching, `match_mode: "starts_with"` for prefix matching, and
`match_mode: "ends_with"` for suffix matching.
```python
{"name": "list", "config": {"values": ["admin", "root"], "case_sensitive": False}}
{"name": "list", "config": {"values": ["/home/lev/agent-control"], "match_mode": "starts_with"}}
{"name": "list", "config": {"values": [".md"], "match_mode": "ends_with"}}
```

### SQL
SQL query validation and dangerous operation detection
```python
{"name": "sql", "config": {"blocked_operations": ["DROP", "DELETE"], "require_limit": True}}
```

### JSON
Structured data validation with JSONPath
```python
{"name": "json", "config": {"path": "$.user.role", "pattern": "admin"}}
```

## Directory Structure

- `builtin/` — Core evaluators (regex, list, json, sql)
- `contrib/` — Community evaluators (PII detection, toxicity, custom)
- `src/` — Shared interfaces and utilities

## Adding Custom Evaluators

Place custom evaluators in `contrib/` and they'll be loaded automatically:

```python
from agent_control_evaluators import Evaluator, EvaluatorConfig, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult
from typing import Any

class MyEvaluatorConfig(EvaluatorConfig):
    threshold: float = 0.5

@register_evaluator
class MyEvaluator(Evaluator[MyEvaluatorConfig]):
    metadata = EvaluatorMetadata(
        name="my-evaluator",
        version="1.0.0",
        description="My custom evaluator",
    )
    config_model = MyEvaluatorConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        # Your logic here
        return EvaluatorResult(
            matched=True,
            confidence=1.0,
            message="Rule triggered",
        )
```

Full guide: https://docs.agentcontrol.dev/concepts/evaluators
