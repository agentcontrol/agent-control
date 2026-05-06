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

Configure Galileo:

```bash
export GALILEO_API_KEY="your-api-key"
export GALILEO_CONSOLE_URL="https://console.demo-v2.galileocloud.io"
```

If the scorer requires explicit project resolution, set:

```bash
export GALILEO_PROJECT_ID="00000000-0000-0000-0000-000000000000"
```

Optional scorer settings:

```bash
export GALILEO_LUNA_METRIC="toxicity"
export GALILEO_LUNA_THRESHOLD="0.5"
```

Run:

```bash
cd examples/galileo_luna
uv run python setup_controls.py
uv run python demo_agent.py
```
