# Cursor × Agent Control × Galileo Protect

A `beforeSubmitPrompt` hook for Cursor that blocks prompts containing **secrets**
(AWS keys, GitHub tokens, etc.) or **PII** (emails, phone numbers, names, SSNs,
credit cards, …) before the prompt ever leaves the developer's machine.

The hook is intentionally thin. **All policy lives in Agent Control.** Adding a
new check (toxicity, prompt injection, custom regex) is a config edit, not a
hook edit.

---

## Architecture

```mermaid
flowchart LR
    subgraph Laptop["Developer's laptop"]
        Cursor["Cursor IDE"]
        Hook["before_submit_protect_guardrails.py<br/>(@control + agent_control.init)"]
        ACS[("Agent Control server<br/>localhost:8000<br/>(Docker)")]
        PG[(postgres)]
        UI["AC UI<br/>localhost:4000<br/>(Docker)"]
    end

    subgraph Cloud["Galileo Cloud"]
        Protect["Protect API<br/>/v1/protect/invoke"]
        Logs["Project log streams<br/>+ Protect Traces"]
    end

    Cursor -->|stdin: prompt JSON| Hook
    Hook -->|"@control evaluation"| ACS
    ACS --> PG
    ACS --> UI
    ACS -->|"galileo.luna2 evaluator<br/>(stage_type=local + ruleset)"| Protect
    ACS -->|"observability events"| ACS
    Hook -.->|"GalileoLogger.add_protect_span<br/>(reuses Protect trace_id)"| Logs
    Hook -->|stdout: continue / deny| Cursor
```

Two guardrails are attached to one AC agent:

| Control | Evaluator | Where it runs | What it catches |
|---|---|---|---|
| `block-secrets-v4` | `regex` | locally inside the AC server | AWS / GitHub / Anthropic / OpenAI / Stripe / Slack / JWT / PEM private key |
| `block-pii-v4` | `galileo.luna2` (`stage_type=local`) | AC server calls Galileo Protect with the ruleset in the request body | email, phone, name, SSN, credit card, address, IP, URL — anything Luna-2's `input_pii` detects |

When AC's `Luna2Evaluator` calls Protect, Galileo records a real Protect trace.
The hook also writes a per-prompt trace to your project's log stream via
`GalileoLogger.add_protect_span`, **reusing the same `trace_id`** — so clicking
through in the project view lands on the actual Protect call. No second
Protect roundtrip.

---

## Why "stage_type=local"?

Galileo Protect supports two ways to ship rulesets:

- **central** — ruleset is stored on Galileo against a stage. Every caller of
  the stage gets the same rules. Good for org-wide policy you don't want clients
  to redefine.
- **local** — caller sends `prioritized_rulesets` in the *payload* on every
  invoke. The stage is just a project anchor (it owns no rules of its own).
  Good for fast iteration on rules without re-deploying anything Galileo-side.

We use **local** because the policy lives in AC's control config — AC's
`Luna2Evaluator` builds the ruleset from that config and ships it on every call.
One source of truth, no Galileo-side ruleset to keep in sync. The senior dev
note that drove this: *"the protect API seems like a good endpoint to continue
to use… stage==local mode that we can use to send RuleSets in the payload…
get rid of all other.. which adds latency in the hot path."*

---

## What `@control()` does

The hook is a few lines:

```python
@control()
async def check_prompt(prompt: str) -> str:
    return prompt   # no-op — the work happens in the decorator

await check_prompt(prompt_from_cursor)
```

The decorator:

1. Takes the function's `prompt` argument (the SDK's input-name preference list
   includes `prompt`) and binds it to AC's `selector.path = "input"`.
2. Calls AC's `/api/v1/evaluation` with `step={type: llm, name: check_prompt, input: prompt}`, `stage: pre`.
3. AC iterates **every** control attached to the agent. Regex runs locally in
   the AC server; `galileo.luna2` calls out to Galileo Protect.
4. AC short-circuits on the first deny.
5. If anything denies → SDK raises `ControlViolationError(control_name=…)`.
6. SDK also POSTs an observability event per control evaluated to
   `/api/v1/observability/events`, which is what populates the AC UI dashboard.

The hook just translates `ControlViolationError` → Cursor's deny shape and
return-success → Cursor's allow shape. It doesn't know there's a regex check or
a Luna-2 check; it doesn't talk to Galileo. Adding a third control tomorrow
(toxicity, prompt injection, …) is a `setup.py` edit. The hook stays untouched.

---

## What happens when a Cursor prompt is submitted

```mermaid
sequenceDiagram
    participant U as Developer
    participant C as Cursor
    participant H as Hook (Python)
    participant A as AC server
    participant P as Galileo Protect
    participant G as Galileo project

    U->>C: types prompt + Enter
    C->>H: stdin {prompt}
    H->>H: agent_control.init()
    H->>A: @control() → /api/v1/evaluation
    par run all attached controls
        A->>A: regex (block-secrets-v4) — local
        A->>P: galileo.luna2 → /v1/protect/invoke (ruleset in body)
        P-->>A: {status, trace_id, metric_results.value}
    end
    A-->>H: {is_safe, matches:[...]}
    H->>A: /api/v1/observability/events (per-control events)
    H->>G: GalileoLogger.add_protect_span (reuses trace_id)
    H->>C: stdout {continue: true | false, user_message}
    C-->>U: prompt sent OR block message
```

If the verdict is **deny**:

- Cursor shows the developer the user_message (`🔒 Blocked: prompt looks like
  it contains a secret/API key.` or `🪪 Blocked: prompt contains PII`).
- AC UI (localhost:4000) shows a deny event under the right control.
- Galileo project's `cursor-hooks` log stream shows a `cursor-hook` trace with
  `decision:deny`. PII denies include a Protect span linking to the Protect
  trace.

If the verdict is **allow**:

- Prompt goes to Cursor's LLM as usual.
- AC UI shows non_match events for the controls that ran.
- Galileo project trace is written with `decision:allow`.

---

## Repo layout

```
.cursor/
  hooks.json                              # Cursor reads this on startup
  hooks/
    before_submit_protect_guardrails.py   # the hook
scripts/
  setup.py                                # provisions AC + Galileo entities (run once)
  test_hook.py                            # 40-prompt battery (15 wrong + 5 right per guardrail)
Dockerfile.server                         # extends AC image w/ luna2 evaluator + 3 sed patches
docker-compose.yml                        # postgres + AC server + AC UI
requirements.txt                          # SDK deps for the venv
.env / .env.example
```

### Why the Dockerfile patches AC's source

The AC base image (`galileoai/agent-control-server:latest`) ships with the
Galileo Luna-2 evaluator source at `/app/evaluators/contrib/galileo` but
doesn't install it into the venv, so AC's evaluator registry never sees it. We
install it from that in-image source with `--no-deps`. The PyPI package's
`[galileo]` extra pulls a newer `agent-control-models` that breaks the server.

Three small `sed`s on top:

1. Add `"input_pii"` to `Luna2Metric` Literal. Galileo Protect's REST API uses
   `input_pii` as the metric name, but AC's evaluator config restricts metrics
   to a whitelist that only includes `pii_detection`. Without this our control
   would fail validation at PUT time.
2. Add `"not_empty"` to `Luna2Operator` Literal. Same reason — Protect uses
   `not_empty`, the whitelist doesn't include it.
3. Patch `_evaluate_local_stage` to forward `stage_name` from config (Protect
   requires it even for local stages — the stage is the project anchor) and
   send `target_value: null` for `not_empty` (AC defaulted to `0`, which makes
   Protect not trigger).

These are tiny diffs in the Dockerfile itself, no upstream fork needed.

---

## Why AC runs locally (per laptop)

Each developer runs the AC stack (postgres + server + UI) in Docker on their
own laptop. The hook talks to `localhost:8000` — sub-millisecond round trip.
Every developer can tweak their controls in `localhost:4000` without affecting
others. Galileo Protect remains the centralized cloud service for the ML check.

Trade-off: the AC observability data is per-laptop. If you want shared dashboards
across the team you'd run a shared AC server somewhere — code change is
just `AGENT_CONTROL_URL`.

---

## Setup

### Prerequisites

- macOS or Linux
- Docker Desktop running
- Python 3.12 (for the venv used by `setup.py` and the hook)
- A Galileo API key

### One-time, per developer

```bash
# 1. Clone, enter the repo, create the venv
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: GALILEO_API_KEY=…, GALILEO_PROJECT=protect-cursor (or your project)
#            GALILEO_CONSOLE_URL=https://console.demo-v2.galileocloud.io  (if self-hosted)

# 3. Bring up Agent Control locally (postgres + server + UI)
docker compose up -d --build
curl -s http://localhost:8000/health     # → {"status":"healthy", ...}

# 4. Provision the agent + controls + Galileo local stage
.venv/bin/python3 scripts/setup.py
#   creates: AC agent  cursor-protect-v4
#            AC controls  block-secrets-v4 (regex), block-pii-v4 (galileo.luna2)
#            Galileo local stage  Cursor Protect v4 (local)
#   safe to re-run; updates in place

# 5. Run the 40-prompt battery (15 wrong + 5 right for each guardrail)
.venv/bin/python3 scripts/test_hook.py
#   → ALL PASS (40/40)

# 6. Restart Cursor (Cmd+Q, then reopen the workspace)
#    Cursor caches hooks.json on startup; until you restart, prompts won't be hooked.
```

### Try it in Cursor

After Cmd+Q and reopen, paste any of these and watch them get blocked:

```
Why is AWS rejecting AKIAIOSFODNN7EXAMPLE in production?
ghp_aBcDeF1234567890aBcDeF1234567890aBcDeF leaked into the repo
Stripe webhook failing — sk_live_<paste-any-stripe-shaped-test-value>

Customer alice.smith@example.com keeps getting 500s
Call John Doe at +1-415-555-0182 about the bug
Investigate the row with SSN 123-45-6789
```

These should pass through:

```
Refactor this function to remove duplicated null checks.
Write unit tests for a JWT refresh token validator.
```

---

## Where to look at the data

| What | Where |
|---|---|
| AC controls + per-control deny/allow counts | http://localhost:4000 → `cursor-protect-v4` |
| Per-prompt Galileo trace (allow + deny) | Galileo console → your project → log streams → `cursor-hooks` |
| Underlying Protect call (every PII check) | Galileo console → Protect Traces |

---

## Adding new patterns / controls

**Secrets regex:** edit `SECRETS_PATTERN` in [scripts/setup.py](scripts/setup.py)
and re-run `.venv/bin/python3 scripts/setup.py`. The script updates the
existing control in place.

**PII categories:** Luna-2's `input_pii` already covers email / phone / name /
SSN / credit card / address / IP / URL out of the box (see the rule in
`PII_CONTROL`). To restrict to specific categories, change `operator` to `any`
and pass `target_value: ["email", "ssn"]` in the control config.

**A new check entirely:** add another control spec in `setup.py`, attach it to
the agent, re-run `setup.py`. Then add a branch to `_deny_message` in
[the hook](.cursor/hooks/before_submit_protect_guardrails.py) so the user-facing
message is right. That's it — the hook code path doesn't change.

---

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `AGENT_CONTROL_URL` | `http://localhost:8000` | AC server base URL |
| `AC_AGENT_NAME` | `cursor-protect-v4` | AC agent the hook evaluates against |
| `GALILEO_API_KEY` | — | Required for any Galileo call (Protect + log_stream traces) |
| `GALILEO_CONSOLE_URL` | `https://console.galileo.ai` | Console URL; API host derived as `api.<rest>` |
| `GALILEO_PROJECT` | — | Galileo project for stages + traces |
| `GALILEO_PROTECT_LOCAL_STAGE` | `Cursor Protect v4 (local)` | Local stage AC's luna2 evaluator points at |
| `GALILEO_LOG_STREAM` | `cursor-hooks` | Project log stream the hook writes traces to |
| `CURSOR_PROTECT_FAIL_MODE` | `allow` | `allow` (fail-open) or `deny` (fail-closed) when a backend is unreachable |
| `CURSOR_PROTECT_DEBUG` | `false` | `true` → print diagnostics to stderr (visible in Cursor → Settings → Hooks) |
| `CURSOR_PROTECT_LOG_RAW` | `false` | `true` → skip PII redaction in logged traces (debug only) |

---

## Troubleshooting

**Prompts go through unblocked after switching hooks.** Cursor caches
`hooks.json` on startup — Cmd+Q (full quit) and reopen the workspace.

**`AC server unreachable`.** `docker ps` for `agent_control_server`. If missing,
`docker compose up -d --build`. Health: `curl http://localhost:8000/health`.

**`ModuleNotFoundError: agent_control` from the hook.** Use the venv:
`.venv/bin/python3` is what `hooks.json` already points at. System Python
(often 3.9 on macOS) doesn't have the SDK.

**No events in AC UI.** The SDK only flushes when `agent_control.ashutdown()`
runs. The hook calls it in a `finally` block — if the process is killed
mid-flight events can be lost. Run `test_hook.py` to verify the path works.

**Galileo project trace has `decision:deny` but no Protect span.** That's a
secrets deny — regex is local to AC, no Protect call to attach. Only PII denies
carry a Protect span (linked via `trace_id` to the actual Protect call).
