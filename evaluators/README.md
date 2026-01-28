# agent-control-evaluators

Evaluator implementations for agent-control.

## Built-in Evaluators

- **regex** - Pattern matching using regular expressions
- **list** - Value matching against allow/deny lists
- **json** - JSON schema validation
- **sql** - SQL query validation using sqlglot

## Optional Evaluators

- **luna2** - Galileo Luna-2 integration (requires `luna2` extra)

## Installation

```bash
pip install agent-control-evaluators

# With Luna-2 support
pip install agent-control-evaluators[luna2]
```
