# Target context demo

End-to-end walkthrough of target-bound controls and the V1 contract that
target context is fixed for the lifetime of the SDK session.

## What this example shows

- `init(target_type=..., target_id=...)` returns the merged effective
  control set: the agent's direct attachments, policy-derived controls,
  and bindings for the supplied target, all in one response.
- `@control()` decorator runs automatically against that merged set with
  no extra configuration.
- `evaluate_controls(...)` defaults its target context from the session,
  so callers don't have to repeat themselves on every call.
- A per-call target that disagrees with the session target is rejected
  with a clear `ValueError`: the SDK supports one target per session;
  re-init to change it.

The example uses `target_type="env"` and `target_id="prod"`. Environment
is one common axis for target context; tenant-level isolation is handled
separately by the namespace seam (`namespace_key`), so the example does
not need to model multi-tenancy to demonstrate target binding.

## Quick run

```bash
# From repo root.
make server-run

# In a separate shell.
uv run python examples/target_context_demo/setup_controls.py
uv run python examples/target_context_demo/demo_agent.py
```

## What you should see

```
=== 1. init() with target context ===
  Effective controls (env=prod): ['block-pii-output', 'block-prod-restricted-input']

=== 2. @control() runs against the merged set ===
  Safe call -> 'You said: hello, target context'
  Pre-stage block (binding):  block-prod-restricted-input
  Post-stage block (direct):  block-pii-output

=== 3. evaluate_controls() defaults target from session ===
  is_safe=True, confidence=1.00

=== 4. per-call target that disagrees with the session is rejected ===
  Rejected as expected: Per-call target context must match the target
  context fixed at init() time. The SDK supports one target per session
  (including no-target sessions); re-init to change it.
```

## Layout the setup script provisions

```
agent: demo-target-bot
  + direct attachment: block-pii-output           (always on; SSN regex on output)

control_bindings:
  + (env, prod) -> block-prod-restricted-input    (only on env=prod; rejects sudo / DROP TABLE / rm -rf)
```

When `init()` is called with `target_type="env", target_id="prod"`, the
server merges these into a single set of two controls. Re-running with
a different `env` value or no target context drops the prod-bound
control from the response.
