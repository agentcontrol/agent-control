# Python 3.14 compatibility audit

Audit date: November 9, 2026. Branch: `feature/quarry-for-controls`.
Implementation baseline: `aff76246c9b003ab3553ea6fa32b5bbc880d0367`.

## Orbit integration remains blocked

There is no supported Python 3.14 Quarry dependency to pin yet. The only published
release, `cisco-project-quarry==0.1.0`, declares `Requires-Python: >=3.11,<3.14`.
Upstream `main` also excludes 3.14. Sources:
[release metadata](https://pypi.org/pypi/cisco-project-quarry/0.1.0/json),
[upstream manifest](https://github.com/cisco-ai-defense/project-quarry/blob/main/pyproject.toml).

Agent Control's Quarry package correctly retains `>=3.12,<3.14`, and the builtin
`quarry` extra still excludes Python 3.14. Removing only those two restrictions
would leave an incompatible upstream distribution. An upstream release or an
approved immutable compatibility fork is needed before widening our metadata.
Do not treat the baseline SHA as an Orbit-compatible Python 3.14 source pin.

## Workspace metadata, builds, and automation

| Area | Finding |
| --- | --- |
| Workspace root and server | `>=3.12,<3.15`; already admit 3.14. |
| Models, engine, telemetry, builtin evaluators, Python SDK | `>=3.12`; already admit 3.14. |
| Budget, Cisco, DefenseClaw, Galileo contrib packages | `>=3.12`; install and pass checks on 3.14. |
| Quarry contrib | `>=3.12,<3.14`; normal `make sync` rejects a 3.14 interpreter. |
| Standalone example manifests | All declare `>=3.12`; no additional metadata exclusion. Their separate framework/application environments were not all executed. |
| Classifiers | The SDK was the only package listing individual Python versions; 3.14 was added after its tests passed. |
| Interpreter selection | `.python-version` remains `3.12.13`. Checks explicitly set `UV_PYTHON=3.14`; changing `setup-python` alone would not override this file. |
| CI | Added a 3.14 matrix job alongside 3.12. It checks core and other contrib packages, with an explicit Quarry exclusion describing the upstream blocker. This is not Quarry support certification. |
| Release builds | Python publishing and the TypeScript release helper use 3.12. Their packaging does not itself forbid consumers on 3.14. The existing release defaults remain unchanged. |
| Server Docker image | Uses `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`; its default was not changed. Orbit's separate image and Bazel toolchain were not modified or validated here. |
| Bazel | This repository has no Bazel configuration to update. |
| Wheels/sdists | Root `make build` successfully built core and all contrib packages under 3.14. Building a universal wheel does not establish compatible `Requires-Python` metadata. |

## Dependency closure

The evaluator's runtime closure was traversed with active extras, including
`sqlglot[c]`. All 23 third-party dependencies below install under CPython 3.14.7
on macOS ARM64. Only our Quarry package and upstream Quarry fail the interpreter
metadata check. These were scratch environments; no production requirement or
upstream wheel metadata was rewritten.

```text
annotated-types==0.8.0       attrs==26.1.0
cachetools==7.2.0           google-re2==1.1.20251105
jsonschema==4.26.0          jsonschema-specifications==2025.9.1
lark==1.3.1                loguru==0.7.3
markdown-it-py==4.2.0       mdurl==0.1.2
orjson==3.13.0             packaging==26.3
pydantic==2.14.1           pydantic-core==2.50.1
pygments==2.21.0           pyyaml==6.0.3
referencing==0.37.0        rich==15.0.0
rpds-py==2026.9.1          sqlglot==30.11.0
sqlglotc==30.11.0          typing-extensions==4.16.0
typing-inspection==0.4.5
```

Binary-only resolution of this complete closure also succeeded for Python 3.14
on Linux x86-64 (`x86_64-manylinux_2_28`). This checks wheel availability, not
execution on that architecture. An attempted Linux x86-64 container run failed
in QEMU while starting the tooling, before Quarry checks could execute.

Native Linux ARM64 diagnostics also passed on CPython 3.14.10: all 54 Quarry
tests, lint, typecheck, offline example, and wheel/sdist build. That disposable
container explicitly used pip's `--ignore-requires-python` and uv's
`UV_NO_SYNC=1`. Its installed upstream metadata still excluded 3.14. The
container's uv dependency checker did not flag that Python restriction, so the
audit also checked it explicitly with `packaging.specifiers.SpecifierSet`;
the result was incompatible. Installer success is not support certification.

## Checks performed

Existing Makefile targets were used with isolated `/tmp` environments and public
PyPI. The normal workspace installation contains no Quarry on 3.14. PostgreSQL
16 was available for the server and SDK integration suites.

| CPython 3.14.7 on macOS ARM64 | Result |
| --- | --- |
| Workspace `make sync` and `uv pip check` | Passed; all installed packages compatible. |
| Models | 76 passed. |
| Telemetry | 20 passed. |
| Engine | 138 passed. |
| Builtin evaluators | 311 passed. |
| Server | 1,040 passed. |
| Python SDK | 754 passed, 2 skipped because optional Galileo extras were absent. |
| Root packaging/build scripts | 6 passed. |
| Budget / Cisco / DefenseClaw / Galileo | 122 / 23 / 26 / 358 passed; package lint and typecheck passed. |
| Core lint | Passed. |
| Core typecheck with mypy 2.4.1 | All 116 source files passed. |
| Quarry, diagnostic installation only | 54 passed; lint, typecheck, offline example, and wheel/sdist build passed. |
| Normal Quarry installation | Blocked by `>=3.12,<3.14`. |
| macOS diagnostic environment dependency check | Fails as expected for local Quarry and `cisco-project-quarry`; runtime success does not remove this incompatibility. |

One server test had assumed that valid JSON nested 10,000 levels always raises
a decoder recursion error. Python 3.14 can decode it. The test now accepts either
an accurate parsed count or an undecodable summary, while requiring the same
502 rejection and empty sanitized error details. All 1,040 server tests also
passed on Python 3.12.13 after this test-only adjustment. Server runtime behavior
was not changed.

## Lockfiles and reproducibility

Python `uv.lock` files are ignored by this repository, including the root and
contrib lockfiles. No Python lock is published by this change. The local root
lock admits `>=3.12,<3.15`; Quarry's local lock retains `>=3.12,<3.14`.

The existing local root lock selected mypy 2.1.0, which reports two `TypeAdapter`
alias errors with Pydantic 2.14.1. The same errors reproduce on 3.12, so they are
not a Python 3.14 runtime regression. Mypy 2.4.1 passes the entire core tree.
A clean dependency resolution was tested separately from the existing local
lock; this distinction matters when reproducing CI from an ignored lockfile.
That clean resolution selected 89 installed packages, including mypy 2.4.1 and
Pydantic 2.14.1, and passed the complete core check command:

```sh
UV_INDEX=https://pypi.org/simple UV_PYTHON=3.14 \
  UV_PROJECT_ENVIRONMENT=/tmp/agent-control-clean314-env \
  make check -o contrib-test -o contrib-lint -o contrib-typecheck
```

The non-Quarry contrib packages were checked independently in separate 3.14
environments. The exclusions above isolate their package environments and the
known Quarry blocker; they do not replace those independent contrib checks.
The CI YAML was parsed and its interpreter selection verified locally; the
hosted GitHub workflow itself has not been run as part of this audit.

The documented diagnostic Quarry checks used `UV_NO_SYNC=1` after explicitly
installing the incompatible distributions into a disposable environment. This
is a compatibility experiment, not an installation recommendation.

## Requirements before giving Orbit a compatible SHA

1. Obtain a reviewed upstream release or immutable fork that declares Python
   3.14 support and passes the compiler/scanner tests and dependency checks.
2. Update our upstream dependency pin, widen the evaluator's Python range, and
   update the builtin extra's interpreter marker together.
3. Re-run normal installs, all Quarry checks, and the complete workspace checks
   without metadata bypasses or the explicit CI Quarry exclusion. Validate the
   actual Orbit Linux/Bazel environment; x86-64 wheel resolution is insufficient.
4. Commit and normally push that validated change, then provide its full SHA.
   The current implementation baseline does not satisfy these conditions.
