# Galileo Luna Evaluator

Integration package for Galileo Luna evaluator.

## Migrating from Luna2

The `galileo.luna2` evaluator ID has been removed. Existing controls that use
`galileo.luna2` should migrate to `galileo.luna` and update their evaluator
configuration to the direct Luna scorer fields (`scorer_label`, `scorer_id`, or
`scorer_version_id`, plus `threshold` and `operator`). If you still need the
legacy Luna2 evaluator, pin `agent-control-evaluator-galileo <8`.

## Install

Canonical install path:

```bash
pip install "agent-control-evaluators[galileo]"
```

Grandfathered convenience aliases remain available:

```bash
pip install "agent-control-sdk[galileo]"
```

Fallback direct wheel install:

```bash
pip install agent-control-evaluator-galileo
```

See full documentation in: https://docs.agentcontrol.dev/concepts/evaluators/contributing-evaluator

Example with usage: https://docs.agentcontrol.dev/examples/galileo-luna
