# OTEL Merged Events Example

This example shows how Agent Control can:

- create one SDK-local control and one server-side control
- merge the resulting control execution events in the SDK
- export the merged batch through the OTEL event sink
- collect the exported OTEL spans locally with an in-memory exporter

## What this example shows

- control creation and agent association on the server
- SDK-local and server-side evaluation in the same protected function call
- merged-event OTEL emission without needing a live collector
- the OTEL attributes emitted for each control execution

## Prerequisites

1. Start the Agent Control server from the repo root:

```bash
make server-run
```

2. Install the example dependencies:

```bash
cd examples/otel_merged_events
uv pip install -e . --upgrade
```

## Setup

Create the demo agent and controls:

```bash
cd examples/otel_merged_events
uv run python setup_controls.py
```

This creates:

- `otel-merged-local-input-check`
- `otel-merged-server-input-check`

Both controls use composite `and` conditions with multiple evaluator leaves so
the exported OTEL spans include representative and aggregate metadata such as
`primary_evaluator`, `primary_selector_path`, `leaf_count`,
`all_evaluators`, and `all_selector_paths`.

## Run

Run the demo script:

```bash
cd examples/otel_merged_events
uv run python demo_agent.py
```

The script prints:

- the protected function result
- the number of OTEL spans collected
- one OTEL span per reconstructed control execution event

This example uses an in-memory OTEL exporter so you can inspect the spans
locally. In a production setup, the same merged-event sink can export to an
OTLP endpoint instead.
