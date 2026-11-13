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
shows aggregate enforcement counts, while the **Events** tab provides a
**Recent executions** drill-down with trace/span/request correlation, control
and rule identity, action, and duration.
When the DefenseClaw integration is enabled, it includes exact blocked input,
raw request body, and enforcement reason by default. Monitor labels event
payloads as **Full content**, **Redacted content**, or **Metadata only** when
DefenseClaw explicitly reports their disclosure state. Events from other
evaluators receive no privacy label unless they report that state. Treat access
to full-content events as access to sensitive workload data.
