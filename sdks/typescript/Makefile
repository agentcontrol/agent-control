SHELL := /bin/bash

.PHONY: help install install-no-frozen speakeasy-install generate generate-check lint typecheck test build release-check publish-dry-run publish clean

help:
	@echo "TypeScript SDK Makefile targets"
	@echo "  make install            - install dependencies (frozen lockfile)"
	@echo "  make speakeasy-install  - download pinned Speakeasy CLI"
	@echo "  make generate           - generate client into src/generated"
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

generate-check: generate
	git diff --exit-code -- src/generated

lint:
	pnpm run lint

typecheck:
	pnpm run typecheck

test:
	pnpm run test

build:
	pnpm run build

release-check:
	$(MAKE) -C ../.. openapi-spec-check
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
