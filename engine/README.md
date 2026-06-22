# Agent Control Engine

The engine is the runtime that evaluates controls, resolves selectors, and runs rules. It is used by the server and SDK to apply control logic consistently.

## What this package provides

- Rule discovery via Python entry points
- Selector evaluation and payload extraction
- Rule execution and result aggregation
- Cached rule instances for performance

## Rule discovery

```python
from agent_control_engine import discover_rules, list_rules

discover_rules()
print(list_rules())
```

Full guide: https://docs.agentcontrol.dev/components/engine
