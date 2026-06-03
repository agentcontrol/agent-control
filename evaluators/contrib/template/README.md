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

The template uses `{{NAME}}` for that package identifier. It does not use `{{ORG}}`.

Keep the public evaluator reference separate from the package identifier:

- `{{ENTRY_POINT}}` is the user-facing evaluator name and should match
  `EvaluatorMetadata.name` in your package code.
- Single-evaluator packages can keep that public name flat, such as `budget`.
- Packages that expose a family of evaluator ids should namespace it, such as
  `cisco.ai_defense` or `galileo.luna`.

## Scaffold a new contrib package

1. Copy the template and rename the manifest:

   ```bash
   cp -r evaluators/contrib/template evaluators/contrib/<name>
   mv evaluators/contrib/<name>/pyproject.toml.template \
     evaluators/contrib/<name>/pyproject.toml
   ```

2. Replace placeholders in `pyproject.toml`:

   - `{{NAME}}` -> contrib package identifier
   - `{{ENTRY_POINT}}` -> public evaluator reference / `EvaluatorMetadata.name`
   - `{{EVALUATOR}}` -> evaluator module path segment (for example `budget` or `ai_defense`)
   - `{{CLASS}}` -> evaluator class name
   - `{{AUTHOR}}` -> authoring team

   For a package with one primary evaluator, `{{ENTRY_POINT}}` is often just `<name>`. For a
   package that groups provider-specific evaluators, use `<name>.<evaluator_id>`.

   The template starts new packages at `0.1.0`; change that if your release plan differs.
   Also replace the copied `README.md` with package-specific install, configuration, and usage
   docs before your first build or publish. Then confirm the package `version` reflects your
   release plan and that the `agent-control-evaluators` / `agent-control-models` dependency
   floors match the compatibility floor you intend to support. Keep those dependency floors
   aligned with the builtin extra you add below before you commit the new package.

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

In `pyproject.toml`, replace `<minimum-compatible-version>` intentionally before the
first build. For an in-repo contrib package on the shared Agent Control release train,
use the current monorepo release version. For an independently maintained package,
choose and document the minimum supported Agent Control version explicitly.

## Expected repo wiring

After the new package exists as a real contrib package, wire it into the repo contract:

1. Add the extra to `evaluators/builtin/pyproject.toml`:

   ```toml
   [project.optional-dependencies]
   <name> = ["agent-control-evaluator-<name>>=<minimum-compatible-version>"]
   ```

   Keep this extra on the current monorepo release line. The release build rewrites builtin
   dependency floors to the active release version before publishing
   `agent-control-evaluators`, so a lower source floor here would not survive into the
   published extra metadata.

2. Add the workspace source pin to `evaluators/builtin/pyproject.toml`:

   ```toml
   [tool.uv.sources]
   agent-control-evaluator-<name> = { path = "../contrib/<name>", editable = true }
   ```

3. Add the package to `tool.semantic_release.version_toml` in the root `pyproject.toml`:

   ```toml
   "evaluators/contrib/<name>/pyproject.toml:project.version",
   ```

   The repo's release automation discovers real contrib packages automatically via
   `scripts/contrib_packages.py`, so once the package has a real `pyproject.toml` and the
   builtin extra / uv source wiring above is in place, `scripts/build.py` and
   `.github/workflows/release.yaml` will pick it up without additional manual edits.

Until those steps are done, the package is still scaffolding rather than a real contrib package.

Docs: https://docs.agentcontrol.dev/concepts/evaluators/contributing-evaluator
