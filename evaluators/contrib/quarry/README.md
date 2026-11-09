# Project Quarry evaluator

Optional `quarry.policy` evaluates one reviewed [Project Quarry](https://github.com/cisco-ai-defense/project-quarry)
DSL rule over Agent Control's recursive `Step`. A rule match triggers the control's
configured action. Local symbolic rules run without credentials, network calls, or
Galileo records. Model adapters, semantic probers, external text resources, compiled
byte uploads, rule parameters, and policy authoring are outside this integration.

## Install

Use Python **3.12 or 3.13**, matching Quarry's supported Python range. Python
**3.13** is the validated integration target for Orbit deployments that bundle
Quarry; Agent Control core can continue running on Python 3.14 without Quarry.

```sh
pip install agent-control-evaluator-quarry
# Or the convenience extra, on Python 3.12–3.13:
pip install 'agent-control-evaluators[quarry]'
```

Install in each SDK/server environment that executes the control. The package is
discovered through the `agent_control.evaluators` entry point; core installations
do not load Quarry. The convenience extra excludes Quarry on Python 3.14 because
Quarry does not support it. Direct installation reports the Python incompatibility.
Quarry is alpha; this integration pins `cisco-project-quarry==0.1.0` for DSL stability.

Python 3.14 remains blocked by that upstream release's `Requires-Python` metadata,
even though diagnostic runtime tests pass when metadata enforcement is bypassed.
See the [Python 3.14 compatibility audit](PYTHON314.md) for workspace checks,
dependency findings, and the requirements for an Orbit-compatible source pin.

## Control configuration

```json
{
  "description": "Detect reading a secret followed by an HTTP send",
  "enabled": true,
  "execution": "server",
  "scope": {"step_types": ["trace", "session"], "stages": ["post"]},
  "condition": {
    "selector": {"path": "*"},
    "evaluator": {
      "name": "quarry.policy",
      "config": {
        "rule": "rule \"Read then send\"\ncondition:\n    has_sequence(\"read_secret\", \"send_http\")\n",
        "session_mode": "continuous",
        "timeout_ms": 10000,
        "max_messages": 10000
      }
    }
  },
  "action": {"decision": "deny"}
}
```

Submit a `trace` or `session` root `Step` through the existing evaluation API.
The evaluator uses the complete runtime step supplied by `evaluate_with_context`,
regardless of selector output. Direct `evaluate` accepts a `Step` or its serialized
object. No hierarchy is fetched from storage or accumulated between requests.
Choose one evaluation scope to avoid evaluating a trace twice, once alone and once
inside its session.

## Step conversion and boundaries

- Trace and session steps are containers. Put event content in `children`, in
  chronological order; leave container `input`/`output` empty (`None`, `""`, `[]`,
  or `{}`). Non-empty container summaries cause an error to avoid dropping or
  double-counting events. Trace children may be `trace`, `llm`, or `tool` steps.
- LLM string input adds a user message; string output adds an assistant message.
  Input may instead be an OpenAI message array, or `{"messages": [...]}`. Arrays
  represent cumulative history and must extend the exact messages already emitted;
  the shared prefix is included once. A structured output must be a complete
  assistant message, including any `tool_calls`. Divergent/stale snapshots error;
  use string input for an incremental user turn. LLM children are unsupported.
- A tool step becomes an assistant function call, followed by its nested children,
  then a tool result if `output` is not `None`. Arguments stay structured through
  JSON encoding; structured results become JSON text. For calls already emitted
  by an LLM, set `context.tool_call_id` to the original ID. Name and arguments must
  agree. Independent tool steps receive deterministic IDs; the converter never
  guesses which pending assistant call a tool executes.
- `Step.tools` uses Quarry's OpenAI function-definition format. Definitions must
  remain identical within each scan. Context fields other than `tool_call_id`,
  names of containers/models, and `ground_truth` are not conversation messages.
- Unknown child types, nested sessions, ambiguous payloads, and hierarchies deeper
  than 32 levels produce explicit errors. Quarry validates roles, tool links,
  arguments, and its standard input/resource limits without truncation.

Sessions require `session_mode`; there is no implicit default:

| Mode | Meaning |
| --- | --- |
| `per_trace` | Scan each child trace independently; match if any trace matches, after every trace completes. Sequences cannot span traces. |
| `continuous` | Concatenate ordered child traces into one conversation. Sequences may span traces. Supply one session's events, with unique tool-call IDs and consistent tool definitions. |

Sessions may only contain trace children. In continuous mode, later LLM histories
must include the earlier traces' conversation prefix. Use `per_trace` for independent
conversations or traces whose histories restart. Boundaries are not synthetic messages;
the policy sees no session/trace IDs. Coverage is limited to the events supplied.

## Results, errors, and caching

Successful results include `matched_rules`, `completion_state`, `scan_count`, the
policy digest, and the session mode when applicable. Empty input or a hierarchy
without messages returns a non-match without error. Invalid DSL or missing resources
reject evaluator construction. The existing evaluator factory caches each instance
by its full configuration; compilation occurs once per instance. Changing rule
source or limits creates another instance. Scans keep request state local.

Invalid conversations, input-limit failures, timeouts, skipped rules, truncation,
and other incomplete scans return `matched=False`, confidence zero, and `error`.
Partial matches never become a decision, including when a later session trace fails.
The existing engine applies its configured error/action policy (deny controls fail
closed). Raw Quarry diagnostics and conversation content are omitted from errors.
The timeout covers the whole evaluation, including all independent session scans;
Quarry's input limits also apply. `max_messages` is a per-conversation limit.

## Local development

From the repository root:

```sh
make -C evaluators/contrib/quarry sync
make -C evaluators/contrib/quarry check
make -C evaluators/contrib/quarry example
make -C evaluators/contrib/quarry build
make contrib-verify
```

The example runs fully offline after installation. Tests use the real pinned Quarry
compiler/scanner for matching, tool linkage, message histories, and session boundaries.
Upstream failure states are injected only for focused error-path coverage.
