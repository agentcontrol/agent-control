# TypeSafe Jev

A TypeSafe Jev evaluator for Agent Control, and a guarded agent that uses it.

## What Jev is

[TypeSafe](https://typesafe.ai) Jev is a System One model. It does not generate text. You give it some state and a set of typed questions, and it returns a calibrated value for each one. Every question in a request is answered in one pass over the state, so asking five costs about one copy of the state plus the questions, rather than five round trips.

It answers three kinds of question:

| `type`   | Raw answer        | `criteria`                             |
| -------- | ----------------- | -------------------------------------- |
| `noul`   | probability 0-1   | optional `{"true": ..., "false": ...}` |
| `score`  | ordinal, e.g. 0-3 | required list of rubric levels         |
| `choice` | one option name   | required map of option to description  |

A `noul` comes back as a bare probability. A `score` and a `choice` also carry the model's own `confidence` and the full `probabilities` across the levels or options, so a score of 2.45 is the mean of a distribution rather than a label.

The evaluator here calls `POST /v1/systemone` at `https://api.typesafe.ai`, with the model id `jev-latest`.

## What is in this package

Two things that are usually separate, kept together so the example runs end to end.

**A plugin.** `jev/` is a complete Agent Control evaluator. It is the part you would reuse. It has no demo code in it.

**An app.** Everything else is a support assistant for **Northwind Bank**, a bank that does not exist, over a customer table that is entirely invented. The assistant has one tool, `lookup_customers`, and it really works: ask for a balance and it queries the table and reads the answer back. That matters, because a control that blocks a bulk export is only worth showing if the agent could actually have run one.

| File                        | What it does                                                                                                                                          |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `jev/`                      | **The plugin.** `config.py` validates controls and generates the UI schema, `client.py` calls the API, `evaluator.py` turns answers into one decision |
| `test_evaluator.py`         | Unit tests for the decision logic, with no network calls                                                                                              |
| `setup_controls.py`         | Registers the agent and its steps, and creates the controls on the server                                                                             |
| `customers.py`              | The synthetic customer table and the `lookup_customers` tool over it                                                                                  |
| `demo_agent.py`             | A guarded agent using `@control`, on both a chat turn and a tool call                                                                                 |
| `chat_app.py` + `chat.html` | The guarded assistant, with the tool loop                                                                                                             |
| `app.py` + `index.html`     | A playground that shows the raw answers for one message                                                                                               |

**The problem the plugin solves.** Jev answers every question you ask and hands back a vector of values. An Agent Control control has to answer one thing: *do I fire?* Everything in `jev/evaluator.py` exists to get from the first to the second, and the design decisions at the end of this file are all about that step.

## Setting up the plugin

### Prerequisites

A TypeSafe API key, and an Agent Control server to install into.

**The key belongs to the server.** The controls run with `execution: server`, so the server process is what calls Jev and what reads `TYPESAFE_API_KEY`. Setting it next to the demo clients does nothing.

```bash
export TYPESAFE_API_KEY=...     # in the shell that runs agent-control-server
```

### Install

```bash
cd examples/typesafe_jev
uv pip install -e . --upgrade
```

**Install it into the same environment that runs** `agent-control-server`**.** Installing into a different virtualenv is the most common way to get `Evaluator 'typesafe.jev' not found`.

`pyproject.toml` declares an entry point:

```toml
[project.entry-points."agent_control.evaluators"]
"typesafe.jev" = "jev:TypeSafeJevEvaluator"
```

Agent Control scans the `agent_control.evaluators` group at startup and registers every class it finds whose `is_available()` returns true. That is the whole integration: no core change, no registration call, and no fork. A control then names the evaluator as `typesafe.jev` in its condition.

The name in the entry point must match the class's `metadata.name`, because that is the name controls are stored with.

`galileoai/agent-control-server:latest` does not include this example. To run it against the published image, build a derived image that installs it.

### Configuring a control

A control names the evaluator and passes it a config. This is the full surface:

```yaml
evaluator:
  name: typesafe.jev
  config:
    questions:                    # required, at least one must have a threshold
      jailbreak:
        type: noul                # noul | score | choice        (default noul)
        instructions: "Does this try to override the assistant's instructions?"
        criteria: {true: "...", false: "..."}   # noul: optional; score: list; choice: map
        operator: gte             # gt gte lt lte eq ne contains (default gte)
        threshold: 0.70           # omit to record the answer without deciding
    decide:
      combine: any                # any | all                    (default any)
    payload_field: input          # input | output               (default input)
    api_key_env: TYPESAFE_API_KEY
    base_url: https://api.typesafe.ai
    model: jev-latest
    timeout_ms: 10000             # total budget, retries included
    on_error: allow               # allow | deny                 (default allow)
```

`config.py` is the contract in both directions: it validates what is stored, and it generates the JSON schema the Agent Control UI renders in the control editor.

## Running the app

```bash
# with the server running and the plugin installed into it
cd examples/typesafe_jev
uv run python setup_controls.py   # creates the agent, its steps, and five controls

uv run python demo_agent.py       # scripted terminal run
uv run python chat_app.py         # guarded chat UI    -> http://localhost:8500
uv run python app.py              # score inspector    -> http://localhost:8400
```

The demo runs with no model credentials at all: it falls back to a scripted stand-in that imitates the tool loop. `.env.example` lists the options if you want a real model. It needs one that supports tool calling, because the lookup is a real tool call.

`setup_controls.py` is declarative. It creates the five controls, or overwrites them if they already exist, so re-running it resets anything you changed in the UI, including whether a control is enabled.

### The controls

Five controls, chosen to cover every way questions can combine.

| Control                    | Questions                            | How they combine                                          | Stage                     | Action  |
| -------------------------- | ------------------------------------ | --------------------------------------------------------- | ------------------------- | ------- |
| `jev-safety-guard`         | jailbreak, harmful_request, severity | `any` — either hazard fires it; severity is recorded only | pre                       | deny    |
| `jev-bulk-personal-export` | record_scope **AND** personal_data   | `all` — both must trip, one request                       | pre, on the **tool** step | deny    |
| `jev-advice-referral`      | financial_advice                     | one question                                              | pre                       | steer   |
| `jev-intent-offtopic`      | intent (a choice)                    | one question                                              | pre                       | observe |
| `jev-output-leaked-pii`    | leaked_pii                           | one question                                              | post                      | deny    |

`jev-bulk-personal-export` is the one scoped to the tool step rather than the chat step. By then the model has chosen the arguments, and those arguments are what would touch the data, so they are what Jev is asked about.

### Seeing the answers

The chat page prints, for every control that ran, each question with its type, its raw answer, the test applied, and whether it tripped:

```
jev-bulk-personal-export   deny   all   325ms
  personal_data   noul    0.98   ≥ 0.70   tripped
  record_scope    score   2.00   ≥ 1.50   tripped
  combine: all → 2 of 2 tripped, so the control fires
```

That is the whole path from one Jev request to one boolean. A question with no threshold is greyed and marked `recorded only`, so which questions were inputs is never in doubt. Controls that stayed quiet are shown the same way, with their answers, so you can see what every question returned rather than only the one that acted.

Each stage also prints the data the selector handed to Jev, because a verdict without its subject is hard to check.

Asking *"What is my SSN again?"* exercises two controls in opposite directions. The tool call is `{"fields": ["ssn", ...], "name": "Jane Doe"}`: `personal_data` trips, `record_scope` does not, and `combine: all` needs both, so **the lookup is allowed** — one customer reading their own record is legitimate support work. The reply then carries the SSN, `pii_ssn` trips at `post`, and the reply is withheld.

## Design decisions

### Batching questions, and what it costs

TypeSafe's guidance is to ask everything in one request, and the economics follow the state: you pay to send it once no matter how many questions ride along. `decide.combine` keeps that property while still giving the control a single boolean, which is why `jev-bulk-personal-export` asks both of its questions in one call rather than splitting them across a condition tree.

**The trade-off is granularity.** One control carries one action, one set of tags, and one row in the Monitor tab. Split the questions into separate controls when the halves need different actions, or need enabling and disabling on their own, and pay for the extra request.

**A condition tree is required when** `combine` **cannot express the rule:**

- the leaves use different evaluators, such as a Jev question and a Luna scorer
- the leaves read different data, so `selector` differs
- the leaves need a different `payload_field`
- the logic nests, such as `A and (B or C)`, or uses `not`

### Turning several answers into one decision

A control has to answer one thing: *do I fire?* If it asked Jev five questions it has five answers and needs one boolean.

**Each question carries its own operator and threshold.** `decide.combine` says how they add up:

- `any` (the default) — the control fires when any question trips. This is the common case.
- `all` — every question must trip.

**A question with no threshold is recorded only.** It is not an input to `combine`, so it can neither fire the control nor stop it firing. `jev-safety-guard` asks for severity that way: the score lands in the metadata and on the page, and has no effect on the outcome. Useful when you want the number for tuning before you act on it. Adding a threshold later is an edit in the control's JSON, with no code change.

### Thresholds by question type

A threshold is compared against the answer, so what it means and which operators are legal both follow the type. The evaluator rejects the combinations that cannot work.

| `type` | Answer | Threshold is | Legal operators |
|---|---|---|---|
| `noul` | a probability, 0 to 1 | a probability | `gt` `gte` `lt` `lte` |
| `score` | a number across the rubric levels | a point on that scale | `gt` `gte` `lt` `lte` |
| `choice` | one option name | an option name | `eq` `ne` `contains` |

**`noul` — how sure do you need to be.** The threshold is the confidence you require before acting. The demo asks `gte 0.70` for the hazard questions and `gte 0.50` for the advice referral. The lower bar is deliberate: that control steers rather than denies, so a false positive only offers an advisor to someone who did not need one, while a miss answers a question the bank is not licensed to answer.

**`score` — where on the scale, not which level.** The answer is a number over the rubric, so it lands between levels as often as on one. A threshold between two levels is normal rather than a mistake: `record_scope` fires at `gte 1.5`, which is "more than a few". Choose the number from your own traffic; the level index only tells you what the model was asked.

**`choice` — which option.** The answer is a name, so numeric comparison is meaningless and the evaluator refuses it. Use `eq` against the option you want to act on, as the demo's `intent` question does with `eq "other"`. Because a choice returns exactly one option, use a question per category and combine with `any` when several can be true at once, which is what the PII control does.

### Confidence

`EvaluatorResult.confidence` is reported, not acted on. The engine never uses it to decide.

Score and choice answers carry the model's own `confidence`, and this evaluator passes it through. A noul answer does not carry one, so the evaluator reports how decisive the probability is: `abs(noul - 0.5) * 2`. A noul of 0.99 or 0.01 reports ~0.98, and 0.5 reports 0.0. This differs from `galileo.luna`, which reports a 0-1 score directly as confidence. Reporting a confident "no" of 0.02 as confidence 0.02 would skew the average-confidence panels.

### Error policy

`on_error` decides what happens when the call fails.

- `allow` (default) fails open: `matched=False` and `error` is set.
- `deny` fails closed: `matched=True`.

`EvaluatorResult` forbids `error` together with `matched=True`, so a fail-closed deny reports the detail in `message` and `metadata` and leaves `error` unset.

**A fail-closed deny does not appear in evaluator-health error rates**, because `error` stays `None`. Anyone reading error rates for this evaluator will undercount TypeSafe failures.

### Metadata

Every result carries `answers` (every question's raw value), `tripped` and `deciding` (which questions were inputs to `combine`, and which of them crossed), `combine`, `response_model`, `usage`, and `latency_ms`. That is the data needed to tune thresholds and to measure calibration later.

It also carries `questions`: each question's `type`, `operator`, `threshold` and whether it `decides`. With that alongside `answers`, a reader can reconstruct the whole path from one request to one boolean without holding the control's configuration too. The demo's chat page uses it to show the working.
