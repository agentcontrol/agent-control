# Agent Control Engine

Core evaluation logic for Agent Control.

## Responsibilities

- **Evaluator Discovery**: Auto-discover evaluators via Python entry points
- **Selector Evaluation**: Extract data from payloads using selector paths
- **Evaluator Execution**: Run evaluators against selected data
- **Caching**: Cache evaluator instances for performance

## Evaluator Discovery

The engine provides the public API for evaluator discovery:

```python
from agent_control_engine import discover_evaluators, list_evaluators

# Discover all evaluators (runs once, safe to call multiple times)
discover_evaluators()

# Get all available evaluators
evaluators = list_evaluators()  # Returns dict[str, EvaluatorClass]

# Access a specific evaluator
regex_evaluator = evaluators.get("regex")
```

Evaluators are discovered via the `agent_control.evaluators` entry point group. Discovery:
1. Scans all installed packages for the entry point
2. Loads each evaluator class
3. Checks `is_available()` to verify dependencies
4. Registers available evaluators

## Key Functions

| Function | Description |
|----------|-------------|
| `discover_evaluators()` | Scan entry points and register evaluators |
| `list_evaluators()` | Get all registered evaluators (triggers discovery) |
| `ensure_evaluators_discovered()` | Ensure discovery has run |
| `get_evaluator_instance(config)` | Get cached evaluator instance |
| `evaluate_control(control, payload)` | Evaluate a single control |
