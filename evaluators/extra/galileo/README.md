# Agent Control Evaluator - Galileo

Galileo Luna2 evaluator for agent-control.

## Installation

```bash
pip install agent-control-evaluator-galileo
```

Or via the convenience extra from the main evaluators package:
```bash
pip install agent-control-evaluators[galileo]
```

## Available Evaluators

| Name | Description |
|------|-------------|
| `galileo.luna2` | Galileo Luna-2 runtime protection |

## Configuration

Set the `GALILEO_API_KEY` environment variable:
```bash
export GALILEO_API_KEY=your-api-key
```

## Usage

Once installed, the evaluator is automatically discovered:

```python
from agent_control_evaluators import discover_evaluators, get_evaluator

discover_evaluators()
Luna2Evaluator = get_evaluator("galileo.luna2")
```

Or import directly:

```python
from agent_control_evaluator_galileo.luna2 import Luna2Evaluator, Luna2EvaluatorConfig

config = Luna2EvaluatorConfig(
    stage_type="local",
    metric="input_toxicity",
    operator="gt",
    target_value=0.5,
    galileo_project="my-project",
)

evaluator = Luna2Evaluator(config)
result = await evaluator.evaluate("some text")
```

## Documentation

- [Galileo Protect Overview](https://v2docs.galileo.ai/concepts/protect/overview)
- [Galileo Python SDK Reference](https://v2docs.galileo.ai/sdk-api/python/reference/protect)
