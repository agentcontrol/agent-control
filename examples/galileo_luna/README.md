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

Configure exactly one Galileo credential.

For most OSS users, only an API key is required. This uses public API-key auth
and calls the public scorer API:

```bash
export GALILEO_API_KEY="your-api-key"
export GALILEO_CONSOLE_URL="https://console.demo-v2.galileocloud.io"
```

`GALILEO_CONSOLE_URL` is optional when using the production console URL.
`GALILEO_LUNA_API_URL` is not required for this path. The client uses
`GALILEO_API_URL` when set, otherwise it derives the API URL from
`GALILEO_CONSOLE_URL`.

For deployments that use service-to-service internal auth, the deployment
environment should inject the API internal secret instead of an API key:

```bash
# Set by deployment tooling, not by normal OSS users.
export GALILEO_API_SECRET_KEY="your-api-secret"
```

OSS users do not need to set `GALILEO_API_SECRET_KEY` manually for the public
API-key path. Deployment tooling may also set a custom scorer API endpoint and
CA bundle. Use these only when the scorer API is not reachable through the
default public API URL derivation, or when the endpoint uses a private CA:

```bash
export GALILEO_LUNA_API_URL="https://api.default.svc.cluster.local:8088"
export GALILEO_LUNA_CA_FILE="/etc/ssl/internal/ca.crt"
```

`GALILEO_LUNA_API_URL` overrides the scorer API URL in either auth mode.
`GALILEO_LUNA_CA_FILE` is only needed for endpoints that are not trusted by the
system CA store.

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

Setting both `GALILEO_API_KEY` and `GALILEO_API_SECRET_KEY` is an error; unset
one so the auth mode can be inferred.

Run:

```bash
cd examples/galileo_luna
uv run python setup_controls.py
uv run python demo_agent.py
```
