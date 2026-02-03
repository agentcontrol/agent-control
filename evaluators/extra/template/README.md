# Evaluator Package Template

This template provides a starting point for creating new evaluator packages for agent-control.

## Setup

1. Copy this template: `cp -r template/ {{org}}/`
2. Replace placeholders in pyproject.toml.template:
   - `{{ORG}}`: Your organization name (e.g., `acme`)
   - `{{EVALUATOR}}`: Evaluator name (e.g., `toxicity`)
   - `{{CLASS}}`: Python class name (e.g., `ToxicityEvaluator`)
   - `{{AUTHOR}}`: Author name
3. Rename to `pyproject.toml`
4. Create your evaluator in `src/agent_control_evaluator_{{org}}/`
5. Register via entry point in pyproject.toml

## Directory Structure

```
{{org}}/
├── pyproject.toml
├── src/agent_control_evaluator_{{org}}/
│   ├── __init__.py
│   └── {{evaluator}}/
│       ├── __init__.py
│       ├── config.py      # Extends EvaluatorConfig
│       └── evaluator.py   # Extends Evaluator, uses @register_evaluator
└── tests/
    ├── __init__.py
    └── test_{{evaluator}}.py
```

## Entry Point Naming Convention

Use `org.evaluator_name` format (e.g., `acme.toxicity`).

This naming convention:
- Uses dots (`.`) as separators for external evaluators
- Distinguishes from built-in evaluators (no namespace) and agent-scoped evaluators (colon separator)

## Implementation Pattern

Your evaluator should:

1. **Extend `EvaluatorConfig`** for configuration:

```python
from agent_control_evaluators import EvaluatorConfig

class MyEvaluatorConfig(EvaluatorConfig):
    threshold: float = 0.5
    # ... other config fields
```

2. **Extend `Evaluator` and use `@register_evaluator`**:

```python
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult

@register_evaluator
class MyEvaluator(Evaluator[MyEvaluatorConfig]):
    metadata = EvaluatorMetadata(
        name="myorg.myevaluator",  # Must match entry point
        version="1.0.0",
        description="My custom evaluator",
    )
    config_model = MyEvaluatorConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        # Your evaluation logic here
        return EvaluatorResult(
            matched=...,
            confidence=...,
            message=...,
        )
```

## Testing

Run tests with:
```bash
cd evaluators/extra/{{org}}
uv run pytest
```

## Publishing

Build and publish your package:
```bash
uv build
uv publish
```

Once published, users can install via:
```bash
pip install agent-control-evaluator-{{org}}
```

The evaluator will be automatically discovered via entry points when used alongside agent-control.
