# Galileo Luna Evaluator

Integration package for Galileo Luna evaluator.

## Migrating from Luna2

The `galileo.luna2` evaluator ID has been removed. Existing controls that use
`galileo.luna2` should migrate to `galileo.luna` and update their evaluator
configuration to use the direct Luna scorer fields. `scorer_id` is required;
`scorer_label` and `scorer_version_id` are optional. `scorer_version_id` is a
deprecated optional compatibility identifier; Orbit currently invokes the
scorer's current default version. The evaluator calls the
URL configured by `GALILEO_LUNA_INVOKE_URL`; the target must support the Luna
scorer invoke request/response contract and internal Galileo secret auth. Also
set `threshold` and `operator` as needed. If you still need the legacy Luna2
evaluator, pin
`agent-control-evaluator-galileo <8`.

The optional evaluator `config` mirrors Orbit's allowlisted scorer-invoke
configuration. Supported keys are `threshold`, `score_threshold`, and
`request_timeout_seconds`; unsupported keys are rejected locally before an HTTP
request is made.

Agent Control always sends an Orbit execution timeout shorter than its HTTP
deadline. When `request_timeout_seconds` is omitted, it defaults to 80% of the
configured HTTP timeout (8 seconds for the default 10-second deadline).

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
