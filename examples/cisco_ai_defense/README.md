# Cisco AI Defense Chat Inspection Examples

This directory contains examples:

- Direct API demo : `chat_inspect_demo.py` — calls Cisco AI Defense Chat Inspection directly and blocks based on `InspectResponse.is_safe`.
- Combined decorator demo: `chat_guarded_all.py` — safe→safe, unsafe request (pre), safe→unsafe response (post)
- Decorator + server-managed controls (PRE+POST): `chat_guarded_all.py` — uses @agent_control.control() with server-managed controls to guard prompts and responses automatically.
- Decorator POST-only focus: `chat_guarded_post.py` — user asks for someone’s email; the simulated model responds with `jsmith@gmail.com`, demonstrating POST-stage PII blocking.

## Prerequisites

- API Key for Cisco AI Defense Chat Inspection
- Python 3.12+
- `uv` package manager

## Environment

Export the following variables:

```
export AI_DEFENSE_API_KEY="<your-api-key>"
# Optional: override the default Inspect endpoint
export AI_DEFENSE_API_URL="https://us.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat"
# Optional: request timeout in seconds (default: 15)
export AI_DEFENSE_TIMEOUT_S="15"
```

Auth header used: `X-Cisco-AI-Defense-API-Key: <AI_DEFENSE_API_KEY>`

## Run (Direct API Demo)

```
cd examples/cisco_ai_defense
uv sync
uv run chat_inspect_demo.py
uv run chat_inspect_demo.py --debug  # also prints raw responses for allowed and blocked
```

### What It Does

- Evaluates sample user prompts (pre) and blocks if `is_safe` is `false`.
- If the prompt is safe, simulates a model response and evaluates it (post), blocking if unsafe.
- Includes a toxic model response example (e.g., "You are an idiot and I hate you!") that should be blocked on the post-check.
- Prints a concise result for each case, including any response fields returned by the API that help explain the decision (when available).

### Notes

- This demo does not seed or rely on Agent Control server policies. It is intended for quick validation of Chat Inspection behavior and latency.
- The request payload is sent as a chat message array. If your deployment expects additional fields, adjust the `build_request_payload()` helper in `chat_inspect_demo.py` accordingly.
- Network/HTTP errors are surfaced with a clear message and the test case continues.

### Troubleshooting

- Missing API key: ensure `AI_DEFENSE_API_KEY` is set.
- Invalid URL: verify `AI_DEFENSE_API_URL` or omit to use the default.
- Timeouts: increase `AI_DEFENSE_TIMEOUT_S`.
- Schema mismatches: enable `--debug` to print raw responses (for both allowed and blocked results).

## Run (Decorator + Server Controls Demo)

1) Ensure the server is running and you have an API key (X-API-Key)

   - Preferred: install the evaluator into the workspace venv, then run the server normally:

     ```bash
     uv pip install -e evaluators/contrib/cisco
     make server-run
     ```

2) Install the Cisco AI Defense evaluator (this repo package) into the server environment, or run `make sync` at the repo root if developing locally. Provide `AI_DEFENSE_API_KEY` in the server environment.

3) Seed controls and attach them to your agent by name:

```
export AGENT_CONTROL_URL="http://localhost:8000"
export AGENT_CONTROL_API_KEY="<server-api-key>"
export AGENT_NAME="ai-defense-demo"   # or your chosen agent name
uv run setup_ai_defense_controls.py
```

4) Run the guarded examples:

```
uv run chat_guarded_all.py --agent-name ai-defense-demo
uv run chat_guarded_post.py --agent-name ai-defense-demo
```

Or using the example Makefile directly from repo root:

```
make -C examples/cisco_ai_defense seed
make -C examples/cisco_ai_defense decorator-post-run
make -C examples/cisco_ai_defense decorator-all-run
```

### What It Does

- Applies server-managed pre and post controls (using `cisco.ai_defense`) around the decorated function.
 - `chat_guarded_all.py`: demonstrates both PRE and POST when applicable.
 - `chat_guarded_post.py`: safe prompt that produces a toxic response, which should be blocked by POST checks.
 - Controls are attached directly to the agent by name (no policy assignment), so reruns are idempotent and non-destructive.

### Troubleshooting

- Evaluator not found: ensure the server has the evaluator package installed and entry points discovered (`/api/v1/evaluators` lists `cisco.ai_defense`).
- Missing keys: set both `AGENT_CONTROL_API_KEY` (server) and `AI_DEFENSE_API_KEY` (server env for evaluator calls).
 - If controls with the same names already exist for another agent, this demo uses unique control names derived from your `AGENT_NAME`, so reruns are safe.

 
