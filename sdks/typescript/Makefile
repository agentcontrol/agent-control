SHELL := /bin/bash

SPEAKEASY_VERSION ?= v1.721.5-rc.0

.PHONY: help install install-no-frozen speakeasy-install generate generate-check lint typecheck test build clean

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

install:
	pnpm install --frozen-lockfile

install-no-frozen:
	pnpm install

speakeasy-install:
	SPEAKEASY_VERSION=$(SPEAKEASY_VERSION) ./scripts/install-speakeasy.sh

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

clean:
	rm -rf dist .speakeasy/tmp-generated
