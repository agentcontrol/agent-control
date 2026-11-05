# Prepare runtime inputs once per evaluation

Implemented locally on the exact Agent Control source used by the cache experiment:
`7f30597a9e69895abedfac38c54d8416ba79dcf2`.
Worktree: `/private/tmp/ac-prepare-input-once-20261104`.
Branch: `codex/prepare-runtime-input-once-20261104`.

## What changes

ControlEngine creates a preparation scope for each process() call. Read-only
Galileo LLM and Luna evaluators opt into reusing the selected input by Step
identity and selector path. Their clients reuse the normalized/validated record
by input identity, provider and payload side. Distinct selectors and payload
sides keep their own preparation. Custom evaluators retain independent wildcard
selections by default.

Every scorer still receives its own request with its own scorer configuration,
authenticated execution context and result. There is no score cache or Redis
change. The scope is cleared on completion, failure and cancellation; nested and
concurrent scopes are isolated. Outside an engine scope the old per-call behavior
is retained. Generated record creation timestamps now belong to the shared
preparation; scorer execution duration and downstream request context remain
per invocation. Prepared selected data and records must be treated as read-only.

This is a coordinated engine/builtin/Galileo-provider source change. It is not a
standalone provider wheel that can be installed against older core packages;
package dependency floors need to be coordinated before a package release.

## Validation

- Engine: 138 tests passed.
- Builtin evaluators: 314 tests passed, including isolation/failure/cancellation.
- Galileo provider: 365 tests passed, including five real scorer HTTP calls per
  evaluation with one preparation, selector/payload distinctions, consecutive
  tenant contexts and compatibility with a mutating custom evaluator.
- All three affected packages passed their Makefile lint/typecheck targets.
- New performance regression tests failed against the original engine/clients
  (4 failed, 2 passed) and passed with the change.
- Server: 1,019 tests passed. SDK: 756 tests passed.
- Root lint and typecheck passed for all workspace packages.
- Git diff whitespace check passed. Repository dependency/lockfiles unchanged.

Tests ran in an isolated Python 3.12.7 environment with galileo-core 4.6.1. The
configured corporate package mirror was unavailable; dependencies were installed
from public PyPI without changing global settings or repository lockfiles. These
are local validation results, not immutable deployed-image qualification.

## Offline preparation benchmark

Synthetic inputs; 30 measured pairs after five warm-up pairs, alternating order.
Each scorer still serializes a separate outbound record. No HTTP, Redis, DB or
model traffic. This measures preparation only, not end-to-end latency or p99.

| Input | Controls | Before median ms | After median ms | Saved ms |
| --- | ---: | ---: | ---: | ---: |
| small_llm | 5 | 0.1592 | 0.0501 | 0.1090 |
| small_llm | 10 | 0.2998 | 0.0660 | 0.2339 |
| trace_100_spans | 5 | 12.0978 | 2.7916 | 9.3062 |
| trace_100_spans | 10 | 23.5444 | 3.1715 | 20.3728 |

The small LLM N5 case saves about 0.11 ms locally, so this is not evidence of a
fix for the observed 2,500 ms client p99. Larger traces offer more opportunity:
the synthetic 100-span N10 case saves about 20 ms of preparation. No percentage
in this microbenchmark should be presented as a production latency improvement.

Reproduce after installing the Galileo development dependencies:

```sh
python evaluators/contrib/galileo/benchmarks/prepare_inputs.py
```

## Next step

Before any deployment, review this prototype against the intended current branch
and coordinate package versions. To investigate the LLM p99, prioritize timings
for authorization, full cache lookup, downstream connection/queue wait and retries.
A future R4 A/B requires a new bounded experiment with matching inputs/resources,
phase timing, exact windows, correctness checks and restoration. The prior R4
experiment remains completed/restored. No new deployment or LT was performed.
