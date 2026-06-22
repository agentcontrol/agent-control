# Agent Control Built-in Rules

Built-in rules provide common checks like regex matching, list matching, JSON validation, and SQL validation. They are discovered automatically via Python entry points and used by the server and SDK runtime.

## What this package provides

- `regex` rule for pattern matching
- `list` rule for allow/deny lists
- `json` rule for schema validation
- `sql` rule for query validation

## Install

```bash
pip install agent-control-rules
```

## Discover rules

```python
from agent_control_rules import discover_rules, list_rules

discover_rules()
print(list_rules())
```

Full guide: https://docs.agentcontrol.dev/concepts/rules/built-in-rules
