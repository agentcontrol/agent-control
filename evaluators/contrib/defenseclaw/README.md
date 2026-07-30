# DefenseClaw evaluators

This package exposes two global external evaluators for Agent Control:

- `defenseclaw.rule_pack` validates a versioned DefenseClaw rule pack.
- `defenseclaw.opa_policy` validates a versioned DefenseClaw OPA policy configuration.

Install both evaluators with:

```bash
pip install "agent-control-evaluators[defenseclaw]"
```

The configuration contracts and JSON Schemas are implemented and discoverable. Both evaluator
classes intentionally execute as no-ops: they return `matched=False` without contacting or
installing any DefenseClaw runtime or OSS package.
