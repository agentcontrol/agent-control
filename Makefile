.PHONY: help sync openapi-spec openapi-spec-check test test-extras test-all test-models test-sdk lint lint-fix typecheck check build build-models build-server build-sdk publish publish-models publish-server publish-sdk hooks-install hooks-uninstall prepush evaluators-test evaluators-lint evaluators-lint-fix evaluators-typecheck evaluators-build galileo-test galileo-lint galileo-lint-fix galileo-typecheck galileo-build sdk-ts-generate sdk-ts-overlay-test sdk-ts-name-check sdk-ts-generate-check sdk-ts-build sdk-ts-test sdk-ts-lint sdk-ts-typecheck sdk-ts-release-check sdk-ts-publish-dry-run sdk-ts-publish

# Workspace package names
PACK_MODELS := agent-control-models
PACK_SERVER := agent-control-server
PACK_SDK    := agent-control
PACK_ENGINE := agent-control-engine
PACK_EVALUATORS := agent-control-evaluators
OPENAPI_SPEC_PATH := server/.generated/openapi.json

# Directories
MODELS_DIR := models
SERVER_DIR := server
SDK_DIR    := sdks/python
TS_SDK_DIR := sdks/typescript
ENGINE_DIR := engine
EVALUATORS_DIR := evaluators/builtin
GALILEO_DIR := evaluators/extra/galileo

help:
	@echo "Agent Control - Makefile commands"
	@echo ""
	@echo "Setup:"
	@echo "  make sync            - uv sync all workspace packages at root (single .venv for all)"
	@echo ""
	@echo "Run:"
	@echo "  make server-<target> - forward to server targets (e.g., server-help, server-alembic-upgrade)"
	@echo "  make openapi-spec    - generate runtime OpenAPI spec at $(OPENAPI_SPEC_PATH)"
	@echo "  make openapi-spec-check - verify OpenAPI generation succeeds"
	@echo ""
	@echo "Test:"
	@echo "  make test            - run tests for core packages (server, engine, sdk, evaluators)"
	@echo "  make test-extras     - run tests for extra evaluators (galileo, etc.)"
	@echo "  make test-all        - run all tests (core + extras)"
	@echo "  make sdk-ts-test     - run TypeScript SDK tests"
	@echo ""
	@echo "Quality:"
	@echo "  make lint            - ruff check for all members"
	@echo "  make lint-fix        - ruff check --fix (auto-fix) for all members"
	@echo "  make typecheck       - mypy for all members"
	@echo "  make check           - run test, lint, and typecheck"
	@echo "  make sdk-ts-lint | sdk-ts-typecheck | sdk-ts-build | sdk-ts-generate | sdk-ts-overlay-test | sdk-ts-name-check"
	@echo "  make sdk-ts-release-check - run TypeScript SDK publish gate checks"
	@echo "  make sdk-ts-publish-dry-run - run npm publish dry-run for TypeScript SDK"
	@echo ""
	@echo "Build / Publish:"
	@echo "  make build           - build wheels for all members"
	@echo "  make publish         - publish all members (ensure credentials configured)"
	@echo "  make build-models | build-server | build-sdk"
	@echo "  make publish-models | publish-server | publish-sdk"
	@echo ""
	@echo "Git hooks:"
	@echo "  make hooks-install   - install repo-local git hooks (pre-push)"
	@echo "  make hooks-uninstall - restore default .git/hooks"
	@echo "  make prepush         - run pre-push checks locally"

# ---------------------------
# Setup
# ---------------------------

sync:
	uv sync --all-packages

# ---------------------------
# OpenAPI spec
# ---------------------------

openapi-spec:
	uv run --package $(PACK_SERVER) python server/openapi.py --output $(OPENAPI_SPEC_PATH)

openapi-spec-check: openapi-spec
	test -s $(OPENAPI_SPEC_PATH)

# ---------------------------
# Run
# ---------------------------

# ---------------------------
# Test
# ---------------------------

test: server-test engine-test sdk-test evaluators-test

# Run tests for extra evaluators (not included in default test target)
test-extras: galileo-test

# Run all tests (core + extras)
test-all: test test-extras

# Run tests, lint, and typecheck
check: test lint typecheck

# ---------------------------
# Quality
# ---------------------------

lint: engine-lint evaluators-lint
	uv run --package $(PACK_MODELS) ruff check --config pyproject.toml models/src
	uv run --package $(PACK_SERVER) ruff check --config pyproject.toml server/src
	uv run --package $(PACK_SDK) ruff check --config pyproject.toml sdks/python/src

lint-fix: engine-lint-fix evaluators-lint-fix
	uv run --package $(PACK_MODELS) ruff check --config pyproject.toml --fix models/src
	uv run --package $(PACK_SERVER) ruff check --config pyproject.toml --fix server/src
	uv run --package $(PACK_SDK) ruff check --config pyproject.toml --fix sdks/python/src

typecheck: engine-typecheck evaluators-typecheck
	uv run --package $(PACK_MODELS) mypy --config-file pyproject.toml models/src
	uv run --package $(PACK_SERVER) mypy --config-file pyproject.toml server/src
	uv run --package $(PACK_SDK) mypy --config-file pyproject.toml sdks/python/src

# ---------------------------
# Build / Publish
# ---------------------------

build: build-models build-server build-sdk engine-build evaluators-build

build-models:
	cd $(MODELS_DIR) && uv build

build-server:
	cd $(SERVER_DIR) && uv build

build-sdk:
	cd $(SDK_DIR) && uv build

publish: publish-models publish-server publish-sdk engine-publish

publish-models:
	cd $(MODELS_DIR) && uv publish

publish-server:
	cd $(SERVER_DIR) && uv publish

publish-sdk:
	cd $(SDK_DIR) && uv publish

# ---------------------------
# Git hooks
# ---------------------------

HOOKS_DIR := .githooks

hooks-install:
	git config core.hooksPath $(HOOKS_DIR)
	chmod +x $(HOOKS_DIR)/pre-push
	@echo "Installed git hooks from $(HOOKS_DIR)"

hooks-uninstall:
	git config --unset core.hooksPath || true
	@echo "Restored default git hooks path (.git/hooks)"

prepush:
	bash $(HOOKS_DIR)/pre-push

sdk-ts-generate: openapi-spec
	$(MAKE) -C $(TS_SDK_DIR) generate

sdk-ts-generate-check: openapi-spec
	$(MAKE) -C $(TS_SDK_DIR) generate-check

sdk-ts-name-check:
	$(MAKE) -C $(TS_SDK_DIR) name-check

sdk-ts-overlay-test:
	$(MAKE) -C $(TS_SDK_DIR) overlay-test

sdk-ts-build:
	$(MAKE) -C $(TS_SDK_DIR) build

sdk-ts-test:
	$(MAKE) -C $(TS_SDK_DIR) test

sdk-ts-lint:
	$(MAKE) -C $(TS_SDK_DIR) lint

sdk-ts-typecheck:
	$(MAKE) -C $(TS_SDK_DIR) typecheck

sdk-ts-release-check:
	$(MAKE) -C $(TS_SDK_DIR) release-check

sdk-ts-publish-dry-run:
	$(MAKE) -C $(TS_SDK_DIR) publish-dry-run

sdk-ts-publish:
	$(MAKE) -C $(TS_SDK_DIR) publish

sdk-ts-%:
	$(MAKE) -C $(TS_SDK_DIR) $(patsubst sdk-ts-%,%,$@)

engine-%:
	$(MAKE) -C $(ENGINE_DIR) $(patsubst engine-%,%,$@)

sdk-%:
	$(MAKE) -C $(SDK_DIR) $(patsubst sdk-%,%,$@)

evaluators-test:
	$(MAKE) -C $(EVALUATORS_DIR) test

evaluators-lint:
	$(MAKE) -C $(EVALUATORS_DIR) lint

evaluators-lint-fix:
	$(MAKE) -C $(EVALUATORS_DIR) lint-fix

evaluators-typecheck:
	$(MAKE) -C $(EVALUATORS_DIR) typecheck

evaluators-build:
	$(MAKE) -C $(EVALUATORS_DIR) build

.PHONY: server-%
server-%:
	$(MAKE) -C $(SERVER_DIR) $(patsubst server-%,%,$@)

# ---------------------------
# Extra Evaluators (Galileo)
# ---------------------------

galileo-test:
	$(MAKE) -C $(GALILEO_DIR) test

galileo-lint:
	$(MAKE) -C $(GALILEO_DIR) lint

galileo-lint-fix:
	$(MAKE) -C $(GALILEO_DIR) lint-fix

galileo-typecheck:
	$(MAKE) -C $(GALILEO_DIR) typecheck

galileo-build:
	$(MAKE) -C $(GALILEO_DIR) build
