SHELL := /bin/bash

.PHONY: help install install-no-frozen speakeasy-install generate overlay-test name-check generate-check lint typecheck test build release-check publish-dry-run publish clean

help:
	@echo "TypeScript SDK Makefile targets"
	@echo "  make install            - install dependencies (frozen lockfile)"
	@echo "  make speakeasy-install  - download pinned Speakeasy CLI"
	@echo "  make generate           - generate client into src/generated"
	@echo "  make overlay-test       - run Python tests for method-name overlay generator"
	@echo "  make name-check         - verify generated method names are ergonomic"
	@echo "  make generate-check     - regenerate and verify src/generated has no diffs"
	@echo "  make lint               - run ESLint"
	@echo "  make typecheck          - run tsc --noEmit"
	@echo "  make test               - run Vitest"
	@echo "  make build              - build package with tsup"
	@echo "  make release-check      - run publish gate checks"
	@echo "  make publish-dry-run    - run npm publish dry-run"
	@echo "  make publish            - publish package to npm"

install:
	pnpm install --frozen-lockfile

install-no-frozen:
	pnpm install

speakeasy-install:
	./scripts/install-speakeasy.sh

generate: speakeasy-install
	./scripts/generate-sdk.sh

overlay-test:
	cd ../.. && uv run --package agent-control-server pytest sdks/typescript/tests/test_generate_method_names_overlay.py

name-check:
	@if command -v rg >/dev/null 2>&1; then \
		MATCH_CMD="rg -n --no-heading"; \
	else \
		MATCH_CMD="grep -REn"; \
	fi; \
	if eval "$$MATCH_CMD 'async\\s+[A-Za-z0-9]+(ApiV[0-9]+|Get|Post|Put|Patch|Delete)\\b' src/generated/sdk"; then \
		echo "Found verbose generated method names. Update generate-method-names-overlay.py rules."; \
		exit 1; \
	fi

generate-check: generate name-check
	git diff --exit-code -- src/generated overlays/method-names.overlay.yaml

lint:
	pnpm run lint

typecheck:
	pnpm run typecheck

test:
	pnpm run test

build:
	pnpm run build

release-check:
	$(MAKE) overlay-test
	$(MAKE) -C ../.. sdk-ts-generate-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) build

publish-dry-run: release-check
	npm publish --dry-run

publish: release-check
	npm publish --provenance

clean:
	rm -rf dist .speakeasy/tmp-generated
