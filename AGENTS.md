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

- `models/`: shared Pydantic v2 models and plugin base classes (`models/src/agent_control_models/`)
- `engine/`: **control evaluation engine and plugin system** — all evaluation logic, plugin discovery, and plugin orchestration lives here (`engine/src/agent_control_engine/`)
- `server/`: FastAPI server (`server/src/agent_control_server/`)
- `sdks/python/`: Python SDK — uses engine for evaluation (`sdks/python/src/agent_control/`)
- `plugins/`: plugin implementations (`plugins/src/agent_control_plugins/`)
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

## Runtime performance

Server API endpoints, engine evaluation, and SDK evaluation are latency-sensitive:

- Avoid per-request/per-control repeated work (parsing/validation/serialization, regex compilation, deep copies) inside hot loops.
- Filter early before spawning work (e.g., stage/tool-scope/locality checks before async fan-out).
- Avoid adding DB/network I/O to hot paths; if unavoidable, batch/cache/amortize and document why.
- Keep logging/tracing cheap in hot paths (no verbose logs in tight loops).

## Testing conventions

All testing guidance (including “behavior changes require tests”) lives in `docs/testing.md`.

## Common change map

- Add API endpoint:
  1) add/adjust models in `models/` (if needed)
  2) add route in `server/src/agent_control_server/endpoints/`
  3) put business logic in `server/src/agent_control_server/services/`
  4) add SDK wrapper in `sdks/python/src/agent_control/`
  5) add tests (server + SDK) and update docs/examples if user-facing

- Add a new evaluator plugin:
  1) implement plugin class extending `PluginEvaluator` in `plugins/src/agent_control_plugins/`
  2) use `@register_plugin` decorator (from `agent_control_models`)
  3) add entry point in `plugins/pyproject.toml` for auto-discovery
  4) add tests in the plugins package
  5) plugin is automatically available to server and SDK via `discover_plugins()`

## Git/PR workflow

- Branch naming: `feature/...`, `fix/...`, `refactor/...`
- Commit messages: conventional commits (e.g. `feat: ...`, `fix: ...`, `docs: ...`)
- Before pushing: `make check` (or `make prepush`).
- Optional: install repo hooks with `make hooks-install` (uses `.githooks/`).
