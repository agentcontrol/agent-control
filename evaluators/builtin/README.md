# Agent Control Evaluators

Built-in evaluators for agent-control.

## Installation

```bash
pip install agent-control-evaluators
```

## Available Evaluators

| Name | Description |
|------|-------------|
| `regex` | Regular expression pattern matching |
| `list` | List-based value matching (allow/deny) |
| `json` | JSON validation (schema, required fields, types) |
| `sql` | SQL query validation |

## Usage

Evaluators are automatically discovered via Python entry points:

```python
from agent_control_evaluators import discover_evaluators, list_evaluators

# Load all available evaluators
discover_evaluators()

# See what's available
print(list_evaluators())
# {'regex': <class 'RegexEvaluator'>, 'list': ..., 'json': ..., 'sql': ...}
```

## External Evaluators

Additional evaluators are available via separate packages:

- `agent-control-evaluator-galileo` - Galileo Luna2 evaluator

```bash
# Direct install
pip install agent-control-evaluator-galileo

# Or via convenience extra
pip install agent-control-evaluators[galileo]
```

## Creating Custom Evaluators

See [AGENTS.md](../../AGENTS.md) for guidance on creating new evaluators.
