# Testing Guide

This file is the in-repo copy of the testing guidance used by the Agent Control docs site. Keep it in sync with the published testing guide when testing conventions change.

## Goals

- Make tests readable and reviewable.
- Prefer verifying behavior through the public contract over internal details.
- Keep the suite reliable: deterministic, minimal flake, clear failures.
- Any behavior change should include a test change. Pure refactors only require test changes if behavior changes.

## What "public contract" means

Public contract is anything exposed to end users and not an internal implementation detail.

Practical mapping in this repo:

- **Server**: HTTP endpoints, request/response schemas, and documented behavior.
- **SDK**: symbols exported from `sdks/python/src/agent_control/__init__.py` and documented behavior.
- **Models**: Pydantic models, fields, validation, and serialization in `models/src/agent_control_models/`.
- **Engine**: stable entrypoints for evaluation behavior. Avoid asserting on private helpers or module structure.

## Prefer testing via public contract

Choose the narrowest user-facing interface that can express the scenario:

1. Server behavior: drive via HTTP endpoints, creating setup state through the API where feasible.
2. SDK behavior: drive via exported SDK APIs.
3. Engine behavior: drive via the engine's stable entrypoints.
4. Only if needed: test internal helpers for hard-to-reach edge cases or performance-sensitive parsing or validation.

Why this rule exists:

- Contract tests survive refactors.
- They catch integration mismatches between models, server, and SDK layers.
- They better reflect how users experience failures.

It is acceptable to use internals when:

- The public route to set up state is disproportionately slow or complex.
- You need to force an otherwise unreachable error path.
- You are testing a pure function where the public API adds no value.

If you use internals, say so explicitly in the test's `# Given:` block. Example: `# Given: seeded DB row directly for speed`.

## Given / When / Then style

Use `# Given`, `# When`, and `# Then` comments to separate intent from mechanics.

Guidelines:

- **Given**: inputs, state, fixtures, mocks, and preconditions.
- **When**: the single action under test.
- **Then**: assertions about outcomes, errors, and side effects.
- Prefer one `When` per test. Split tests unless multiple actions are inseparable.
- Keep comments short and specific.

### Example: unit-level validation

```python
def test_scope_rejects_invalid_step_name_regex() -> None:
    # Given: a scope with an invalid regex
    scope = {"step_name_regex": "("}

    # When: constructing the model
    with pytest.raises(ValueError):
        ControlScope.model_validate(scope)

    # Then: a clear validation error is raised
```

### Example: API-level behavior

```python
def test_create_control_returns_id(client: TestClient) -> None:
    # Given: a valid control payload
    payload = {"name": "pii-protection"}

    # When: creating the control via the public API
    response = client.put("/api/v1/controls", json=payload)

    # Then: the response contains the control id
    assert response.status_code == 200
    assert "control_id" in response.json()
```

### Example: SDK-level behavior

```python
async def test_sdk_denies_on_local_control() -> None:
    # Given: an SDK client and a local deny control
    client = AgentControlClient(base_url="http://localhost:8000")
    controls = [{"execution": "sdk", "action": {"decision": "deny"}, ...}]

    # When: evaluating via the SDK public API
    result = await check_evaluation_with_local(
        client=client,
        agent_name="demo-agent",
        step=Step(type="tool", name="db_query", input={"sql": "SELECT 1"}, output=None),
        stage="pre",
        controls=controls,
    )

    # Then: the evaluation is unsafe
    assert result.is_safe is False
```

## Setup guidance

- Prefer creating records via public endpoints rather than writing DB rows directly.
- Prefer invoking behavior via public entrypoints.
- Avoid asserting on internal or private fields unless they are part of the contract.

Specific guidance:

- **Server**: use HTTP endpoints when practical. The service layer is internal.
- **SDK**: use symbols exported from `sdks/python/src/agent_control/__init__.py`.
- **Database seeding**: direct row insertion is acceptable for migration tests, otherwise prefer public setup flows.

## Evaluator-specific expectations

When adding or changing evaluators, tests should cover at least these three cases:

1. Null or empty input: returns `matched=False` and no error.
2. Normal evaluation: returns the correct `matched` result for the configured threshold or predicate.
3. Infrastructure failure: returns `matched=False` with `error` set, unless the evaluator intentionally uses a different documented error policy.

Additional evaluator rules worth testing when relevant:

- `error` is for infrastructure failures, not normal evaluation outcomes.
- Evaluators are reused across concurrent requests, so avoid request-scoped state on `self`.
- Pre-compiled patterns, timeout handling, and async boundaries should be covered when they are part of the evaluator behavior.

## Running tests

Prefer Makefile targets when available:

- All tests: `make test`
- All checks: `make check`
- Server tests: `make server-test`
- Engine tests: `make engine-test`
- SDK tests: `make sdk-test`

If there is no Makefile target for the task, run the underlying command directly.

Package-specific notes:

- Server tests use the configured test database in `server/Makefile`.
- SDK tests start a local server and wait on `/health`.
- Models tests currently run directly from the `models/` package.

## Practical defaults

- New behavior should come with a focused test.
- Bug fixes should include a regression test when practical.
- Prefer small, specific test fixtures over broad shared setup.
- Keep tests deterministic. Avoid timing-sensitive assertions and unnecessary sleeps.
- When changing shared contracts in `models/`, expect corresponding server and SDK test updates.
