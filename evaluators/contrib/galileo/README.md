# Galileo Luna Evaluator

Integration package for Galileo Luna evaluator.

## Migrating from Luna2

The `galileo.luna2` evaluator ID has been removed. Existing controls that use
`galileo.luna2` should migrate to `galileo.luna` and update their evaluator
configuration to use the direct Luna scorer fields. `scorer_id` is required;
`scorer_label` and `scorer_version_id` are optional. The evaluator calls the
URL configured by `GALILEO_LUNA_INVOKE_URL`; the target must support the Luna
scorer invoke request/response contract and internal Galileo secret auth. Also
set `threshold` and `operator` as needed. If you still need the legacy Luna2
evaluator, pin
`agent-control-evaluator-galileo <8`.

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
