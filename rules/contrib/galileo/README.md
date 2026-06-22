# Galileo Luna Rule

Integration package for Galileo Luna rule.

## Migrating from Luna2

The `galileo.luna2` rule ID has been removed. Existing controls that use
`galileo.luna2` should migrate to `galileo.luna` and update their rule
configuration to the direct Luna scorer fields (`scorer_label`, `scorer_id`, or
`scorer_version_id`, plus `threshold` and `operator`). If you still need the
legacy Luna2 rule, pin `agent-control-rule-galileo <8`.

## Install

Canonical install path:

```bash
pip install "agent-control-rules[galileo]"
```

Grandfathered convenience aliases remain available:

```bash
pip install "agent-control-sdk[galileo]"
```

Fallback direct wheel install:

```bash
pip install agent-control-rule-galileo
```

See full documentation in: https://docs.agentcontrol.dev/concepts/rules/contributing-rule

Example with usage: https://docs.agentcontrol.dev/examples/galileo-luna
