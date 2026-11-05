# Country-Specific Controls

Apply different rules per country (jurisdiction), authored either as one control per country or as one composite control.

## What this example shows

- Per-country rules: block German IBANs only for `DE`, and US Social Security numbers only for `US`
- Two ways to author the same policy, side by side:
  - one control per country: `and(jurisdiction in [CC], rule)`
  - one composite control: `or(and(DE, IBAN rule), and(US, SSN rule))`
- Two ways to send the jurisdiction with each check:
  - `country_controls_context.py`: `evaluate_controls(..., context={"jurisdiction": "DE"})`, selected with `context.jurisdiction`
  - `country_controls_decorator.py`: `@control(step_type="tool")` with a `jurisdiction` function argument, selected with `input.jurisdiction`

No LLM or API key is needed. The scripts stand in for the model answer with fixed text.

## Quick run

```bash
# From repo root
make server-run

# In separate shell, from repo root
uv run python examples/country_controls/country_controls_context.py
uv run python examples/country_controls/country_controls_decorator.py
```

Each script creates its agent and controls, then checks the per-country and composite results for each scenario. It prints PASS or FAIL for each check, and exits non-zero if any check fails. The scripts are safe to re-run.

Full walkthrough: https://docs.agentcontrol.dev/examples/country-controls

## Choosing where the jurisdiction goes

- Use `context.jurisdiction` when the jurisdiction is request metadata, separate from the data being checked. Gateways and non-Python clients send the same `step.context` in the body of `POST /api/v1/evaluation`.
- `@control()` builds the step from the function's arguments and cannot set `step.context`. To use the decorator, pass the jurisdiction as an argument of a tool step and select `input.jurisdiction`. For an LLM step, `input` is a single string, so this path does not resolve.

## Note

A request with no jurisdiction matches no country rule, so all country rules are skipped. If you need a strict default, add a control that matches when the jurisdiction is missing or not covered, for example `and(not(jurisdiction in [DE, US]), or(IBAN rule, SSN rule))`.
