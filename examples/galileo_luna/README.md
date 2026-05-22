# Galileo Luna Direct Evaluator Example

This example shows an Agent Control agent using the direct Galileo Luna evaluator (`galileo.luna`). The evaluator calls Galileo's `/scorers/invoke` API and applies thresholds locally from the control definition.

## What It Shows

- `setup_controls.py` registers an agent and attaches controls.
- `demo_agent.py` runs an agent step protected with `@control`.
- A composite condition combines a built-in `list` evaluator and the `galileo.luna` evaluator.
- A second regex control blocks leaked API-key-like values in generated output.

## Setup

Start the Agent Control server from the repo root:

```bash
make server-run
```

Configure Galileo public API-key auth:

```bash
export GALILEO_LUNA_AUTH_MODE="public"
export GALILEO_API_KEY="your-api-key"
export GALILEO_CONSOLE_URL="https://console.demo-v2.galileocloud.io"
```

For internal deployments, use internal auth instead:

```bash
export GALILEO_LUNA_AUTH_MODE="internal"
export GALILEO_API_SECRET_KEY="your-api-secret"
export GALILEO_API_URL="https://api.default.svc.cluster.local:8088"
```

Optional scorer settings:

```bash
export GALILEO_LUNA_SCORER_LABEL="toxicity"
# Or select by scorer id/version instead of label:
# export GALILEO_LUNA_SCORER_ID="scorer-id"
# export GALILEO_LUNA_SCORER_VERSION_ID="scorer-version-id"
export GALILEO_LUNA_THRESHOLD="0.5"
export GALILEO_LUNA_PAYLOAD_FIELD="output"
```

`GALILEO_LUNA_PAYLOAD_FIELD` is explicit for scalar selected data. This example
selects the agent's drafted reply with `selector.path="output"`, so it sends that
scalar as the scorer `output` field. If a selector returns structured data with
`input` and/or `output` keys, those keys are sent directly and override
`GALILEO_LUNA_PAYLOAD_FIELD`.

If both `GALILEO_API_KEY` and `GALILEO_API_SECRET_KEY`/`GALILEO_API_SECRET` are
set, `GALILEO_LUNA_AUTH_MODE` is required so the client does not silently choose
an auth path.

Run:

```bash
cd examples/galileo_luna
uv run python setup_controls.py
uv run python demo_agent.py
```
