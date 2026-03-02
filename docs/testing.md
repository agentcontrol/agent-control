# Testing guide

## Goals

- Make tests readable and reviewable.
- Prefer verifying behavior through the **public contract** (user-facing surfaces) over internal details.
- Keep the suite reliable: deterministic, minimal flake, clear failures.
- Any behavior change should include a test change (add/adjust). Pure refactors only require test changes if behavior changes.

## What “public contract” means

Public contract is anything exposed to end users and not an internal implementation detail.

Practical mapping in this repo:
- **Server**: HTTP endpoints + request/response schemas (and documented behavior).
- **SDK**: symbols exported from `sdks/python/src/agent_control/__init__.py` (and documented behavior).
- **Models**: Pydantic models/fields/validation/serialization in `models/src/agent_control_models/`.
- **Engine**: stable, intended entrypoints for evaluation behavior (avoid asserting on internal helpers/private module structure).

## Prefer testing via public contract (rule of thumb)

Choose the narrowest user-facing interface that can express the scenario:

1. **Server behavior** → drive via HTTP endpoints (create/setup via API where feasible).
2. **SDK behavior** → drive via exported SDK API.
3. **Engine behavior** → drive via the engine’s stable entrypoints.
4. **Only if needed**: test internal helpers for hard-to-reach edge cases or performance-sensitive parsing/validation.

Why this rule exists:
- Contract tests survive refactors (less coupled to internals).
- They catch integration mismatches between packages (models/server/sdk).
- They better reflect how users experience failures.

When it’s OK to use internals:
- The public route to set up state is disproportionately slow or complex.
- You need to force an otherwise-unreachable error path.
- You’re testing a pure function where the “public API” adds no value.

If you do use internals, say so explicitly in the test’s `# Given:` block (e.g., “Given: seeded DB row directly for speed”).

## Given / When / Then style

Use `# Given`, `# When`, `# Then` comments to separate intent from mechanics. This helps smaller models (and humans) avoid mixing setup/action/assertions, and makes tests easy to scan.

Guidelines:
- **Given**: inputs, state, preconditions (fixtures/mocks/seed data).
- **When**: the single action under test (call a function / make a request).
- **Then**: assertions about outcomes (return value, error, side effects).
- Prefer **one When per test**. If you need multiple actions, split tests unless the steps are inseparable.
- Keep comments short and specific (often one line each).

### Example: unit-level validation

Examples below are illustrative; adjust imports/names and fill in placeholders to match the concrete code under test.

```python
def test_scope_rejects_invalid_step_name_regex() -> None:
    # Given: a scope with an invalid regex
    scope = {"step_name_regex": "("}

    # When: constructing the model
    with pytest.raises(ValueError):
        ControlScope.model_validate(scope)

    # Then: a clear validation error is raised (asserted by pytest)
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
        agent_name=agent_name,
        step=Step(type="tool", name="db_query", input={"sql": "SELECT 1"}, output=None),
        stage="pre",
        controls=controls,
    )

    # Then: the evaluation is unsafe
    assert result.is_safe is False
```

## Setup guidance (contract-first)

- Prefer creating records via **public endpoints** rather than writing DB rows directly.
- Prefer invoking behavior via public entrypoints:
  - Server: HTTP endpoints (the service layer is internal; use it directly only when endpoint setup is impractical).
  - SDK: symbols exported from `sdks/python/src/agent_control/__init__.py`.
- Avoid asserting on internal/private fields unless they are part of the contract (schemas, response fields, documented behavior).

## Running tests (Makefile-first)

Prefer Makefile targets when available:
- All tests: `make test`
- Server tests: `make server-test`
- Engine tests: `make engine-test`
- SDK tests: `make sdk-test`

If there is no Makefile target for a task (e.g., models tests), it’s OK to run the underlying command (e.g., `cd models && uv run pytest`).

Package-specific notes:
- Server tests use a configured test database (see `server/Makefile`; invoked via `make server-test`).
- SDK tests start a local server and wait on `/health` (invoked via `make sdk-test`).
