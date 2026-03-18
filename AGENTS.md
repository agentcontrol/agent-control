# Agent Control: instructions for coding agents

This repo is a Python monorepo managed as a `uv` workspace. Use the existing `make` targets and follow the conventions in `CONTRIBUTING.md`.

## Makefile-first workflow

Prefer running `make <target>` over raw tool commands (`uv ...`, `pytest ...`, `ruff ...`, `mypy ...`). Only run raw commands when there is no Makefile target that accomplishes the intent.

## Quick commands (run from repo root)

- Install/sync deps: `make sync` (runs `uv sync --all-packages`)
- Run all checks: `make check` (tests + ruff + mypy)
- Run all tests: `make test`
- Lint / auto-fix: `make lint` / `make lint-fix`
- Typecheck: `make typecheck`
- Run server: `make server-run` (or `cd server && make run`)

Forwarded targets:
- `make server-<target>` → runs `<target>` in `server/` (e.g. `make server-alembic-upgrade`)
- `make engine-<target>` → runs `<target>` in `engine/`
- `make sdk-<target>` → runs `<target>` in `sdks/python/`

## Repo layout (uv workspace members)

- `models/`: shared Pydantic v2 models and evaluator base classes (`models/src/agent_control_models/`)
- `engine/`: **control evaluation engine and evaluator system** — all evaluation logic, evaluator discovery, and evaluator orchestration lives here (`engine/src/agent_control_engine/`)
- `server/`: FastAPI server (`server/src/agent_control_server/`)
- `sdks/python/`: Python SDK — uses engine for evaluation (`sdks/python/src/agent_control/`)
- `evaluators/builtin/`: builtin evaluator implementations (`evaluators/builtin/src/agent_control_evaluators/`)
- `evaluators/contrib/`: optional evaluator packages (e.g., `evaluators/contrib/galileo/`)
- `ui/`: Nextjs based web app to manage agent controls 
- `examples/`: runnable examples (ruff has relaxed import rules here)

## Code conventions

- Python: 3.12+.
- Formatting/linting: Ruff (line length 100, import sorting via `I` rules).
- Typing: `mypy` is strict (`disallow_untyped_defs = true`); keep code strongly typed.
- Avoid loose typing everywhere: minimize `Any`, avoid untyped dicts, and prefer precise types (`Literal`, `TypedDict`, enums, Pydantic models).
- Reuse types end-to-end: prefer using the same public models/types in internal implementations (don’t “downgrade” to `dict` internally). If no public type fits, introduce a well-named internal type.
- If `Any` is unavoidable, confine it to I/O boundaries and convert to typed models immediately.
- Docstrings: keep docstrings accurate and human-readable. For public APIs and non-obvious logic, use standard Python docstrings (PEP 257) and document `Args`, `Returns`, and `Raises` as applicable; when refactoring, proactively find/update docstrings (and any docs/examples) impacted by signature/type/behavior changes.
- Keep changes scoped: prefer the smallest diff that fixes the issue and matches existing patterns.
- Shared contracts live in `models/`: if you change request/response or shared types, expect follow-up changes in `server/` and `sdks/python/`.
- Imports: prefer top-level imports over local/inline imports. Local imports are acceptable only for: (1) breaking circular dependencies, (2) optional dependencies with try/except, (3) TYPE_CHECKING blocks.
- SQLAlchemy: use the 2.0-style APIs (e.g., `select()` + `AsyncSession.execute()`), avoid legacy `Session.query()`.

## Runtime performance

Server API endpoints, engine evaluation, and SDK evaluation are latency-sensitive:

- Avoid per-request/per-control repeated work (parsing/validation/serialization, regex compilation, deep copies) inside hot loops.
- Filter early before spawning work (e.g., stage/tool-scope/locality checks before async fan-out).
- Avoid adding DB/network I/O to hot paths; if unavoidable, batch/cache/amortize and document why.
- Keep logging/tracing cheap in hot paths (no verbose logs in tight loops).

## Testing conventions

All testing guidance (including "behavior changes require tests") lives in `TESTING.md`.

## Common change map

- Add API endpoint:
  1) add/adjust models in `models/` (if needed)
  2) add route in `server/src/agent_control_server/endpoints/`
  3) put business logic in `server/src/agent_control_server/services/`
  4) add SDK wrapper in `sdks/python/src/agent_control/`
  5) add tests (server + SDK) and update docs/examples if user-facing

- Add a new builtin evaluator:
  1) implement evaluator class extending `Evaluator` in `evaluators/builtin/src/agent_control_evaluators/`
  2) use `@register_evaluator` decorator (from `agent_control_evaluators`)
  3) add entry point in `evaluators/builtin/pyproject.toml` for auto-discovery
  4) add tests in the evaluators/builtin package
  5) evaluator is automatically available to server and SDK via `discover_evaluators()`

- Add an external evaluator package:
  1) copy `evaluators/contrib/template/` as a starting point
  2) implement evaluator class extending `Evaluator` from `agent_control_evaluators`
  3) add entry point using `org.name` format (e.g., `galileo.luna2`)
  4) package is discovered automatically when installed alongside agent-control

## Git/PR workflow

- Branch naming: `feature/...`, `fix/...`, `refactor/...`
- Commit messages: conventional commits (e.g. `feat: ...`, `fix: ...`, `docs: ...`)
- Before pushing: `make check` (or `make prepush`).
- Optional: install repo hooks with `make hooks-install` (uses `.githooks/`).
