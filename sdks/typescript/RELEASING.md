# Releasing the TypeScript SDK

This package publishes to npm as `agent-control`.

## One-time setup

1. Ensure npm ownership for `agent-control` is configured.
2. Add repository secret `NPM_TOKEN` with publish permission.
3. Ensure GitHub Actions has `id-token: write` permission for provenance.

## Pre-release checklist

Run from repo root:

```bash
make sdk-ts-release-check
```

This validates:
- OpenAPI spec can be generated from server code
- Generated client is current
- Lint, typecheck, test, and build all pass

## Local package dry run

Run from repo root:

```bash
make sdk-ts-publish-dry-run
```

This runs the publish gate checks and then executes `npm publish --dry-run`.

## GitHub Actions release flow

Use workflow `.github/workflows/release-sdk-ts.yml`:

1. Trigger manually with `dry_run=true` first.
2. Confirm all checks and packaging output are correct.
3. Trigger again with `dry_run=false` to publish.

The publish run performs:
- `make sdk-ts-generate-check` (this generates OpenAPI from server code, then checks SDK/overlay drift)
- `make sdk-ts-lint`
- `make sdk-ts-typecheck`
- `make sdk-ts-test`
- `make sdk-ts-build`
- `npm publish --provenance`

## Post-publish verification

1. Install from npm in a clean temp project:
   - `npm i agent-control`
2. Confirm import works:
   - `import { AgentControlClient } from "agent-control";`
3. Verify package metadata on npm and GitHub release notes.
