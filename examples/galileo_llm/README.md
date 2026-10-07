# Galileo LLM-as-Judge Direct Evaluator Example

This example shows an Agent Control agent using the direct Galileo LLM-as-judge evaluator (`galileo.llm`). The evaluator calls the same scorer invoke URL as the Luna evaluator and applies thresholds locally from the control definition. It is suited for boolean scorers (e.g. prompt injection detection) where the scorer returns `True`/`False`.

## What It Shows

- `setup_controls.py` registers an agent and attaches three controls.
- `demo_agent.py` runs an agent step protected with `@control`.
- A pre-execution control scores the raw user input with `galileo.llm` and blocks before the LLM runs if the scorer flags it as a prompt injection attempt.
- A composite post-execution control combines a built-in `list` evaluator (fast keyword pre-filter) with `galileo.llm` scoring the LLM output.
- A regex control blocks leaked API-key-like values in generated output.

## Setup

Start the Agent Control server from the repo root:

```bash
make server-run
```

Configure LLM scorer invoke credentials:

```bash
export GALILEO_API_SECRET_KEY="your-api-secret"
export GALILEO_LUNA_INVOKE_URL="http://luna-invoke.internal/api/v1/scorers/invoke"
```

`GALILEO_API_SECRET` can be used instead of `GALILEO_API_SECRET_KEY` if that is how your deployment exposes the internal Galileo JWT signing secret. `GALILEO_LUNA_INVOKE_URL` is shared between the Luna and LLM evaluators — both use the same scorer invoke endpoint.

Required scorer setting:

```bash
export GALILEO_LLM_SCORER_ID="your-scorer-uuid"
```

Optional scorer settings:

```bash
export GALILEO_LLM_SCORER_LABEL="prompt_injection_llm"   # display/metadata label only
export GALILEO_LLM_SCORER_VERSION_ID="version-uuid"      # optional compatibility ID
export GALILEO_LLM_OPERATOR="eq"                         # default: eq (for boolean scorers)
export GALILEO_LLM_PAYLOAD_FIELD="input"                 # default: input
```

`GALILEO_LLM_OPERATOR` and the threshold (`True` by default) work together. For a boolean prompt injection scorer that returns `True` when injection is detected, `operator=eq` and `threshold=True` means: block when the scorer returns `True`.

`GALILEO_LLM_PAYLOAD_FIELD` controls which scorer input side is used when the selector returns a scalar value. The pre-execution control selects `input` (the raw user message) and the post-execution composite control selects `output` (the LLM reply). When a selector returns structured data with `input` and/or `output` keys, those keys are sent directly and override this setting.

If the invoke endpoint uses an internal certificate authority, configure one of:

```bash
export GALILEO_LUNA_INVOKE_CA_FILE="/etc/ssl/internal/luna-invoke-ca.crt"
export AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE="/etc/agent-control/auth-upstream-ca/ca.crt"
```

Run:

```bash
cd examples/galileo_llm
uv run python setup_controls.py
uv run python demo_agent.py
```
