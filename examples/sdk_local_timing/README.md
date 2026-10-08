# SDK-local control timing example

This example runs five synthetic controls through the Python SDK's real
`check_evaluation_with_local` path. It covers list allow/block, regex steer,
SQL block, and JSON validation. Each case uses one control, so its result and
duration have a clear owner.

PR #283 measures the full control condition evaluation. It includes evaluator
work and any wait for an evaluator slot. It excludes control loading and SDK
call overhead. The separate `sdk_call` distribution includes those costs.
These values are not isolated evaluator-call timings.

From the repository root:

```bash
make sync
uv run --package agent-control-sdk python examples/sdk_local_timing/demo.py --iterations 100 --warmup 5
```

The default output is a small per-control p50/p95 table. Pass `--json` for
counts, min, p50, p95 and max values in a machine-readable report. The
`control` number comes from `ControlMatch.execution_duration_ms`; `sdk_call`
is measured around the SDK call by this example.

For a bounded SDK-local throughput smoke, add `--concurrency 8 --iterations 1000`.
The table then includes observed SDK calls per second for each independent
scenario. This uses one Python process and one event loop without a target
request rate; it is not a production capacity number.

The example disables SDK observability for its run and restores the previous
settings afterward. An HTTP mock rejects all outbound requests. No account,
API key, server, Luna scorer, or GPU is needed. The warmup runs are excluded
from the reported nearest-rank p50 and p95 values.

This example does not establish SDK capacity or server/Luna3 throughput. Those
require a configured workload, stack, acceptance thresholds and a separate
load test.
