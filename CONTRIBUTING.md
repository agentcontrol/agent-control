# Contributing to Agent Control

Thanks for taking the time to contribute! This guide covers the process for contributing to Agent Control.

For development setup, architecture details, and code conventions, see the [README](README.md) and [AGENTS.md](AGENTS.md).

## Table of Contents

1. [Integrate Agent Control into Your Agents](#1-integrate-agent-control-into-your-agents)
2. [Contribute New Evaluators](#2-contribute-new-evaluators)
3. [Extend Agent Control](#3-extend-agent-control)
4. [Improve Code and Documentation](#4-improve-code-and-documentation)
5. [Suggest Features and Report Bugs](#5-suggest-features-and-report-bugs)

---

## Before You Start

- **For significant changes, open an issue first.** Discussing your approach ahead of time avoids wasted effort. Changes that were not discussed may be rejected.
- **For small fixes** (typos, minor bug fixes), you can go straight to a pull request.
- **Claim your work.** If you start on an issue, comment on it or assign yourself to avoid duplicate effort.
- Look for issues labeled [good first issue](https://github.com/agentcontrol/agent-control/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) or **help wanted** if you're new.

---

## 1. Integrate Agent Control into Your Agents

We welcome examples showing how Agent Control works with different agent frameworks.

To add an integration example:

1. Create a directory in `examples/` (e.g., `examples/my_framework/`).
2. Include a `README.md` with setup instructions, a `pyproject.toml` for dependencies, and runnable Python files.
3. Update `examples/README.md` to list your new example.
4. Open a PR.

See existing examples in `examples/` for the expected structure.

---

## 2. Contribute New Evaluators

Evaluators are a core extension point. We support two paths:

| Path | Use when | Location |
| --- | --- | --- |
| Built-in | Lightweight deps, broadly useful | `evaluators/src/agent_control_evaluators/builtin/` |
| Contrib | Heavy deps or vendor-specific | `evaluators/contrib/agent-control-evaluator-<org>/` |

**Steps:**

1. Create the evaluator class extending `Evaluator` from `agent_control_models`.
2. Register via `@register_evaluator` and add the entry point in `pyproject.toml`.
3. Add tests and documentation.
4. Run `make evaluators-test` (and ideally `make check`).
5. Open a PR.

For built-in evaluators, add your module to `evaluators/src/agent_control_evaluators/builtin/` and register the entry point in `evaluators/pyproject.toml`.

For contrib evaluators, create a new package under `evaluators/contrib/` with its own `pyproject.toml`. Entry points must be namespaced as `org.evaluator_name`. Add a convenience extra in `evaluators/pyproject.toml` and include the package in the workspace members in the root `pyproject.toml`.

See existing evaluators (e.g., `regex`, `list`) and `AGENTS.md` for detailed conventions and code patterns.

---

## 3. Extend Agent Control

For changes to the core system (new API endpoints, SDK features, engine logic):

1. **Models** (`models/`): Shared Pydantic models and base classes. Change here when adding new API request/response types or evaluator base functionality.
2. **Engine** (`engine/`): Evaluation logic and evaluator discovery. Change here when modifying how controls are evaluated.
3. **Server** (`server/`): FastAPI endpoints and business logic. Change here when adding API endpoints or server functionality.
4. **SDK** (`sdks/python/`): Python client library. Change here when adding user-facing SDK features.
5. **UI** (`ui/`): Next.js web dashboard. Change here for frontend features.

See `AGENTS.md` for the full architecture diagram, dependency flow, and code conventions.

---

## 4. Improve Code and Documentation

Documentation and code quality improvements are always welcome:

- **Typos and clarity fixes**: Open a PR directly.
- **Missing examples**: Add to `docs/` or `examples/`.
- **API documentation**: Docstrings in the code are the source of truth.
- **Architecture guides**: Update files in `docs/`.

Run `make check` before submitting to ensure nothing is broken.

---

## 5. Suggest Features and Report Bugs

### Reporting Bugs

1. **Search first**: Check [GitHub Issues](https://github.com/agentcontrol/agent-control/issues) for duplicates. If you find one, add context in a comment rather than opening a new issue.
2. **Create an issue** with: clear title, steps to reproduce ([minimal example](https://stackoverflow.com/help/minimal-reproducible-example)), expected vs. actual behavior, environment details (OS, Python version, Agent Control version), and full error messages/stack traces.
3. **Keep issues focused.** One topic per issue. Link related issues rather than combining them.

### Suggesting Features

1. **Search first**: Check [existing feature requests](https://github.com/agentcontrol/agent-control/issues?q=is%3Aissue+label%3Aenhancement).
2. **Open an issue** with the `enhancement` label. Describe the use case, explain the value, provide examples, and consider alternatives.
3. Be open to discussion and iteration on your idea.

---

## Contribution Workflow

### Fork, Branch, and PR

1. **Fork** the repository and clone your fork.
2. **Create a branch** with a descriptive name: `feature/...`, `fix/...`, `docs/...`, or `refactor/...`.
3. **Make your changes.** Keep diffs focused. Follow the conventions in [AGENTS.md](AGENTS.md).
4. **Write tests.** All behavior changes require tests. See `docs/testing.md`.
5. **Run checks locally**: `make check` (runs tests, lint, and typecheck).
6. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `perf:`.
7. **Push** and open a PR against `main`. Link related issues (e.g., "Fixes #123").

### Code Review

1. **CI must pass.** All automated checks (tests, lint, typecheck) must be green.
2. **A maintainer will review.** Simple PRs: 2-3 days. Complex PRs: up to a week.
3. **Address feedback** by pushing new commits (don't force-push unless asked).
4. **Merge.** We use squash merge to keep history clean.

If your PR has waited more than a week, feel free to politely ping in the comments.

---

## Acceptable Use of AI Tools

AI tools can help with contributions, but **AI assistance must be paired with meaningful human review and judgment.**

- **Acceptable**: Using AI for boilerplate, understanding unfamiliar code, or generating a starting point that you refine.
- **Not acceptable**: Submitting entirely AI-generated code without review, mass automated contributions, or low-effort spam PRs.

**If the effort to create a PR is less than the effort to review it, that contribution should not be submitted.** We will close PRs that appear to be low-effort AI-generated spam.

---

## Need Help?

- Read `docs/OVERVIEW.md` (architecture), `docs/REFERENCE.md` (API), `docs/testing.md` (testing), and `AGENTS.md` (dev conventions).
- Check `examples/` for integration patterns.
- Search [existing issues](https://github.com/agentcontrol/agent-control/issues).
- Start a [GitHub Discussion](https://github.com/agentcontrol/agent-control/discussions) for open-ended questions.

## License

Agent Control is Apache 2.0 licensed. See [LICENSE](LICENSE) for details.

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
