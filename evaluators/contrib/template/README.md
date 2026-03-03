Creating a Contrib Evaluator
============================

This guide walks you through building and publishing a new evaluator package for agent-control. Start to finish, it takes about 15 minutes.

For a working reference, see the [Galileo evaluator](../galileo/).

Quick Start
-----------

Pick your org name and evaluator name. Everything else derives from these two:

> **Example**: org = `acme`, evaluator = `toxicity`
>
> *   PyPI package: `agent-control-evaluator-acme`
> *   Python package: `agent_control_evaluator_acme`
> *   Entry point: `acme.toxicity`
> *   Evaluator class: `AcmeToxicityEvaluator`

From the repo root:

```bash
cp -r evaluators/contrib/template/ evaluators/contrib/acme/
mv evaluators/contrib/acme/pyproject.toml.template evaluators/contrib/acme/pyproject.toml
```

Edit `pyproject.toml` and replace all placeholders (`{ORG}`, `{EVALUATOR}`, `{CLASS}`, `{AUTHOR}`). Then create the source layout:

```bash
mkdir -p evaluators/contrib/acme/src/agent_control_evaluator_acme/toxicity
mkdir -p evaluators/contrib/acme/tests
touch evaluators/contrib/acme/src/agent_control_evaluator_acme/__init__.py
touch evaluators/contrib/acme/src/agent_control_evaluator_acme/toxicity/__init__.py
touch evaluators/contrib/acme/src/agent_control_evaluator_acme/toxicity/config.py
touch evaluators/contrib/acme/src/agent_control_evaluator_acme/toxicity/evaluator.py
touch evaluators/contrib/acme/tests/__init__.py
touch evaluators/contrib/acme/tests/test_toxicity.py
```

You'll end up with:

```
acme/
├── pyproject.toml
├── src/agent_control_evaluator_acme/
│   ├── __init__.py
│   └── toxicity/
│       ├── __init__.py
│       ├── config.py
│       └── evaluator.py
└── tests/
    ├── __init__.py
    └── test_toxicity.py
```

Writing the Evaluator
---------------------

**Config** - extend `EvaluatorConfig` with your evaluator's settings:

```python
# toxicity/config.py
from pydantic import Field
from agent_control_evaluators import EvaluatorConfig

class AcmeToxicityConfig(EvaluatorConfig):
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    categories: list[str] = Field(default_factory=lambda: ["hate", "violence"])
```

**Evaluator** - extend `Evaluator` and decorate with `@register_evaluator`:

```python
# toxicity/evaluator.py
from typing import Any

from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult

from agent_control_evaluator_acme.toxicity.config import AcmeToxicityConfig

@register_evaluator
class AcmeToxicityEvaluator(Evaluator[AcmeToxicityConfig]):
    metadata = EvaluatorMetadata(
        name="acme.toxicity",        # Must match entry point key exactly
        version="1.0.0",
        description="Acme toxicity detection",
        requires_api_key=True,       # Set if you need external credentials
        timeout_ms=5000,             # Timeout for external calls
    )
    config_model = AcmeToxicityConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        if data is None:
            return EvaluatorResult(matched=False, confidence=1.0, message="No data")

        try:
            score = await self._score(str(data))
            return EvaluatorResult(
                matched=score >= self.config.threshold,
                confidence=score,
                message=f"Toxicity: {score:.2f}",
            )
        except Exception as e:
            # Fail-open on infrastructure errors
            return EvaluatorResult(
                matched=False, confidence=0.0,
                message=f"Failed: {e}", error=str(e),
            )

    async def _score(self, text: str) -> float:
        # Your API call or local logic here
        ...
```

**Entry point** in `pyproject.toml` - this is how discovery finds your evaluator:

```toml
[project.entry-points."agent_control.evaluators"]
"acme.toxicity" = "agent_control_evaluator_acme.toxicity:AcmeToxicityEvaluator"
```

The entry point key (`acme.toxicity`) must exactly match `metadata.name` in the evaluator class. If these don't match, `get_evaluator()` returns `None`.

**Exports** in `toxicity/__init__.py`:

```python
from agent_control_evaluator_acme.toxicity.config import AcmeToxicityConfig
from agent_control_evaluator_acme.toxicity.evaluator import AcmeToxicityEvaluator

__all__ = ["AcmeToxicityEvaluator", "AcmeToxicityConfig"]
```

Testing
-------

Write tests using Given/When/Then style. Cover at least three cases:

1.  **Null input** - returns `matched=False`, no error
2.  **Normal evaluation** - returns correct `matched` based on threshold
3.  **Infrastructure failure** - returns `matched=False` with `error` set (fail-open)

```python
# tests/test_toxicity.py
import pytest
from agent_control_evaluator_acme.toxicity import AcmeToxicityEvaluator, AcmeToxicityConfig

@pytest.fixture
def evaluator() -> AcmeToxicityEvaluator:
    return AcmeToxicityEvaluator(AcmeToxicityConfig(threshold=0.5))

@pytest.mark.asyncio
async def test_none_input(evaluator):
    result = await evaluator.evaluate(None)
    assert result.matched is False
    assert result.error is None

@pytest.mark.asyncio
async def test_score_above_threshold_matches(evaluator, monkeypatch):
    async def _high(self, text):
        return 0.8

    monkeypatch.setattr(AcmeToxicityEvaluator, "_score", _high)
    result = await evaluator.evaluate("test")
    assert result.matched is True
    assert result.error is None

@pytest.mark.asyncio
async def test_api_failure_fails_open(evaluator, monkeypatch):
    async def _fail(self, text):
        raise ConnectionError("timeout")

    monkeypatch.setattr(AcmeToxicityEvaluator, "_score", _fail)
    result = await evaluator.evaluate("test")
    assert result.matched is False
    assert result.error is not None
```

Rules to Know
-------------

**Error handling** - The `error` field is only for infrastructure failures (network errors, API 500s, missing credentials). If your evaluator ran and produced a judgment, that's `matched=True` or `matched=False` - not an error. When `error` is set, `matched` must be `False` (fail-open).

**Thread safety** - Evaluator instances are cached and reused across concurrent requests. Never store request-scoped state on `self`. Use local variables in `evaluate()`.

**Performance** - Pre-compile patterns in `__init__()`. Use `asyncio.to_thread()` for CPU-bound work. Respect `timeout_ms` for external calls.

Before You Submit
-----------------

From the repo root:

```bash
PKG=evaluators/contrib/acme

# Check for leftover placeholders (should print nothing; non-zero exit is OK here)
grep -rn '{ORG}\|{EVALUATOR}\|{CLASS}\|{AUTHOR}' "$PKG"/ || true

# Lint, typecheck, test
(cd "$PKG" && uv run --extra dev ruff check --config ../../../pyproject.toml src/)
(cd "$PKG" && uv run --extra dev mypy --config-file ../../../pyproject.toml src/)
(cd "$PKG" && uv run pytest)

# Verify discovery works
(cd "$PKG" && uv run python -c "
from agent_control_evaluators import discover_evaluators, get_evaluator
discover_evaluators()
ev = get_evaluator('acme.toxicity')
assert ev is not None, 'Discovery failed - entry point key does not match metadata.name'
print(f'OK: {ev.metadata.name}')
")

# Build
(cd "$PKG" && uv build)
```

Publishing
----------

```bash
(cd evaluators/contrib/acme && uv build && uv publish)
```

Users install with `pip install agent-control-evaluator-acme` and the evaluator is discovered automatically.

Reference
---------

*   [Galileo evaluator](../galileo/) - complete working example
*   [Built-in evaluators](../../builtin/src/agent_control_evaluators/) - regex, list, json, sql patterns
