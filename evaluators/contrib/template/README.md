# Contrib Evaluator Template

This directory is scaffolding for a new contrib evaluator package.

It is intentionally excluded from repo automation until you convert it into a real package. In
particular, `template/` does not participate in root `make check`, CI, semantic-release, or
publishing because it ships a `pyproject.toml.template` placeholder instead of a real
`pyproject.toml`.

## Naming contract

Pick `<name>` as a short lowercase single-word identifier such as `galileo`, `cisco`, or
`budget`. That same value should appear in the steady-state package shape:

- directory: `evaluators/contrib/<name>/`
- pip package: `agent-control-evaluator-<name>`
- Python module: `agent_control_evaluator_<name>`
- extra name: `agent-control-evaluators[<name>]`
- entry-point namespace: `<name>.<evaluator_id>`

The template uses `{{NAME}}` for that package identifier. It does not use `{{ORG}}`.

## Scaffold a new contrib package

1. Copy the template and rename the manifest:

   ```bash
   cp -r evaluators/contrib/template evaluators/contrib/<name>
   mv evaluators/contrib/<name>/pyproject.toml.template \
     evaluators/contrib/<name>/pyproject.toml
   ```

2. Replace placeholders in `pyproject.toml`:

   - `{{NAME}}` -> contrib package identifier
   - `{{EVALUATOR}}` -> evaluator snake_case id
   - `{{CLASS}}` -> evaluator class name
   - `{{AUTHOR}}` -> authoring team

   Then confirm the package `version` and the `agent-control-evaluators` /
   `agent-control-models` dependency floors still match the current monorepo version before you
   commit the new package.

3. Add package code and tests:

   - `src/agent_control_evaluator_<name>/`
   - `tests/`

4. Validate the package locally:

   ```bash
   make lint
   make lint-fix
   make typecheck
   make test
   make check
   make build
   ```

## Canonical install docs

Contributor-facing and user-facing package docs should treat this as the canonical install path:

```bash
pip install "agent-control-evaluators[<name>]"
```

Direct wheel installs such as `pip install agent-control-evaluator-<name>` can still be
documented, but they are secondary to the extra on `agent-control-evaluators`.

## Expected repo wiring

After the new package exists as a real contrib package, wire it into the repo contract:

1. Add the extra to `evaluators/builtin/pyproject.toml`:

   ```toml
   [project.optional-dependencies]
   <name> = ["agent-control-evaluator-<name>>=<current-version>"]
   ```

2. Add the workspace source pin to `evaluators/builtin/pyproject.toml`:

   ```toml
   [tool.uv.sources]
   agent-control-evaluator-<name> = { path = "../contrib/<name>", editable = true }
   ```

3. Add the package to the root semantic-release version train in `pyproject.toml`:

   ```toml
   "evaluators/contrib/<name>/pyproject.toml:project.version",
   ```

Until those steps are done, the package is still scaffolding rather than a real contrib package.

Docs: https://docs.agentcontrol.dev/concepts/evaluators/contributing-evaluator
