# Releasing the TypeScript SDK

This package publishes to npm as `agent-control`.

## Release policy

- TypeScript SDK releases are independent from server/monorepo version tags.
- Releases are commit-driven via `semantic-release`.
- Expected release-triggering commit scopes use `sdk-ts`:
  - `feat(sdk-ts): ...` -> minor bump
  - `fix(sdk-ts): ...`, `perf(sdk-ts): ...`, `refactor(sdk-ts): ...`, `chore(sdk-ts): ...` -> patch bump
  - `BREAKING CHANGE` or `!` -> major bump

## One-time setup

1. Ensure npm ownership for `agent-control` is configured.
2. Add repository secret `NPM_TOKEN` with publish permission.
3. Ensure workflow `.github/workflows/release-sdk-ts.yml` has:
   - `contents: write` for release commit/tag
   - `id-token: write` for npm provenance

## Pre-release checks

Run from repo root:

```bash
make sdk-ts-release-check
```

This validates:
- OpenAPI spec can be generated from server code
- Generated client is current
- Lint, typecheck, test, and build all pass

## Local semantic-release preview

Run from `sdks/typescript`:

```bash
pnpm run release:dry-run
```

This previews the next semantic version and release notes without publishing.

## GitHub Actions release flow

Workflow: `.github/workflows/release-sdk-ts.yml`

- Manual preview: `workflow_dispatch` with `dry_run=true`.
- Manual publish: `workflow_dispatch` with `dry_run=false` from `main`.

Release job performs:
- `make sdk-ts-release-check`
- `semantic-release` (updates `package.json` + `CHANGELOG.md`, creates Git tag/release, publishes to npm)

## Post-publish verification

1. Confirm npm version/dist-tag:
   - `npm view agent-control version dist-tags --json`
2. Install from npm in a clean temp project:
   - `npm i agent-control`
3. Confirm import works:
   - `import { AgentControlClient } from "agent-control";`
4. Verify GitHub release/tag and changelog update.
