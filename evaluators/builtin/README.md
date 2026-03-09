# Agent Control Built-in Evaluators

Built-in evaluators provide common checks like regex matching, list matching, JSON validation, and SQL validation. They are discovered automatically via Python entry points and used by the server and SDK runtime.

## What this package provides

- `regex` evaluator for pattern matching
- `list` evaluator for allow/deny lists
- `json` evaluator for schema validation
- `sql` evaluator for query validation

## Install

```bash
pip install agent-control-evaluators
```

## Discover evaluators

```python
from agent_control_evaluators import discover_evaluators, list_evaluators

discover_evaluators()
print(list_evaluators())
```

Full guide: https://docs.agentcontrol.dev/concepts/evaluators/built-in-evaluators
