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
The complementary DefenseClaw watcher can emit post-decision
`ControlExecutionEvent` records through the Agent Control SDK. The agent Monitor
shows aggregate enforcement counts and a **Recent executions** drill-down with
trace/span/request correlation, control and rule identity, action, and duration.
When the DefenseClaw integration is enabled, it includes exact blocked input,
raw request body, and enforcement reason by default. Monitor labels those spans
`UNREDACTED` and renders the content in the execution drill-down. DefenseClaw
operators can explicitly select metadata-only delivery. Treat access to these
events as access to sensitive workload data.
