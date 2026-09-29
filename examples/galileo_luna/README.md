# Galileo Luna Direct Evaluator Example

This example shows an Agent Control agent using the direct Galileo Luna evaluator (`galileo.luna`). The evaluator calls a Luna scorer invoke URL and applies thresholds locally from the control definition.

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

Configure Luna invoke credentials:

```bash
export GALILEO_API_KEY="your-application-api-key"
export GALILEO_API_URL="https://your-galileo-api.example"
export GALILEO_LUNA_INVOKE_URL="https://your-luna-invoke.example/api/v1/scorers/invoke"
```

The application API key is used only to obtain a short-lived, run-scoped scorer grant from Orbit. Configure `agent_control.init()` with `target_type="log_stream"` and the target log-stream ID; Agent Control forwards that target on each evaluation request, and Orbit uses `target_id` as `run_id`. `GALILEO_API_URL` is the Orbit API root. `GALILEO_LUNA_INVOKE_URL` can be either the full scorer invoke URL or a service root that serves `/api/v1/scorers/invoke`. Existing deployments can instead set `GALILEO_API_SECRET_KEY` or `GALILEO_API_SECRET` to keep using the legacy internal JWT flow.

Required scorer setting:

```bash
export GALILEO_LUNA_SCORER_ID="your-scorer-uuid"
```

Optional scorer settings:

```bash
export GALILEO_LUNA_SCORER_LABEL="toxicity"            # display/metadata label only
export GALILEO_LUNA_SCORER_VERSION_ID="version-uuid"  # deprecated compatibility ID
export GALILEO_LUNA_THRESHOLD="0.5"
export GALILEO_LUNA_PAYLOAD_FIELD="output"
```

`GALILEO_LUNA_SCORER_VERSION_ID` is a deprecated optional compatibility
identifier. Orbit currently invokes the scorer's current default version.

`GALILEO_LUNA_PAYLOAD_FIELD` is explicit for scalar selected data. This example selects the agent's drafted reply with `selector.path="output"`, so it sends that scalar as the scorer `output` field. If a selector returns structured data with `input` and/or `output` keys, those keys are sent directly and override `GALILEO_LUNA_PAYLOAD_FIELD`.

If the Luna invoke endpoint uses an internal certificate authority, configure one of:

```bash
export GALILEO_LUNA_INVOKE_CA_FILE="/etc/ssl/internal/luna-invoke-ca.crt"
export AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE="/etc/agent-control/auth-upstream-ca/ca.crt"
```

Run:

```bash
cd examples/galileo_luna
uv run python setup_controls.py
uv run python demo_agent.py --target-id "your-existing-log-stream-id"
```
