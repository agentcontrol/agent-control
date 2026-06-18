# Galileo Luna Direct Evaluator Example

This example shows an Agent Control agent using the direct Galileo Luna evaluator (`galileo.luna`). The evaluator calls runners-api at `/api/v1/scorers/invoke` and applies thresholds locally from the control definition.

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

Configure runners-api credentials:

```bash
export GALILEO_API_SECRET_KEY="your-api-secret"
export GALILEO_RUNNERS_API_URL="http://runners-api:8090"
```

`GALILEO_API_SECRET` can be used instead of `GALILEO_API_SECRET_KEY` if that is how your deployment exposes the internal runners-api JWT signing secret.

Required scorer setting:

```bash
export GALILEO_LUNA_SCORER_ID="your-scorer-uuid"
```

Optional scorer settings:

```bash
export GALILEO_LUNA_SCORER_LABEL="toxicity"            # display/metadata label only
export GALILEO_LUNA_SCORER_VERSION_ID="version-uuid"  # pin a specific scorer version
export GALILEO_LUNA_THRESHOLD="0.5"
export GALILEO_LUNA_PAYLOAD_FIELD="output"
```

`GALILEO_LUNA_PAYLOAD_FIELD` is explicit for scalar selected data. This example selects the agent's drafted reply with `selector.path="output"`, so it sends that scalar as the scorer `output` field. If a selector returns structured data with `input` and/or `output` keys, those keys are sent directly and override `GALILEO_LUNA_PAYLOAD_FIELD`.

If the runners-api endpoint uses an internal certificate authority, configure one of:

```bash
export GALILEO_RUNNERS_API_CA_FILE="/etc/ssl/internal/runners-api-ca.crt"
export AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE="/etc/agent-control/auth-upstream-ca/ca.crt"
```

Run:

```bash
cd examples/galileo_luna
uv run python setup_controls.py
uv run python demo_agent.py
```
