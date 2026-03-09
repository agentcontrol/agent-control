# Agent Control Engine

The engine is the runtime that evaluates controls, resolves selectors, and runs evaluators. It is used by the server and SDK to apply control logic consistently.

## What this package provides

- Evaluator discovery via Python entry points
- Selector evaluation and payload extraction
- Evaluator execution and result aggregation
- Cached evaluator instances for performance

## Evaluator discovery

```python
from agent_control_engine import discover_evaluators, list_evaluators

discover_evaluators()
print(list_evaluators())
```

Full guide: https://docs.agentcontrol.dev/components/engine
