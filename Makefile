.PHONY: help sync test test-models test-sdk lint lint-fix typecheck check build build-models build-server build-sdk publish publish-models publish-server publish-sdk hooks-install hooks-uninstall prepush

# Workspace package names
PACK_MODELS := agent-control-models
PACK_SERVER := agent-control-server
PACK_SDK    := agent-control
PACK_ENGINE := agent-control-engine

# Directories
MODELS_DIR := models
SERVER_DIR := server
SDK_DIR    := sdks/python
ENGINE_DIR := engine

help:
	@echo "Agent Control - Makefile commands"
	@echo ""
	@echo "Setup:"
	@echo "  make sync            - uv sync all workspace packages at root (single .venv for all)"
	@echo ""
	@echo "Run:"
	@echo "  make server-<target> - forward to server targets (e.g., server-help, server-alembic-upgrade)"
	@echo ""
	@echo "Test:"
	@echo "  make test            - run tests for all members"
	@echo ""
	@echo "Quality:"
	@echo "  make lint            - ruff check for all members"
	@echo "  make lint-fix        - ruff check --fix (auto-fix) for all members"
	@echo "  make typecheck       - mypy for all members"
	@echo "  make check           - run test, lint, and typecheck"
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
# Run
# ---------------------------

# ---------------------------
# Test
# ---------------------------

test: server-test engine-test sdk-test

# Run tests, lint, and typecheck
check: test lint typecheck

# ---------------------------
# Quality
# ---------------------------

lint: engine-lint
	uv run --package $(PACK_MODELS) ruff check --config pyproject.toml models/src
	uv run --package $(PACK_SERVER) ruff check --config pyproject.toml server/src
	uv run --package $(PACK_SDK) ruff check --config pyproject.toml sdks/python/src

lint-fix: engine-lint-fix
	uv run --package $(PACK_MODELS) ruff check --config pyproject.toml --fix models/src
	uv run --package $(PACK_SERVER) ruff check --config pyproject.toml --fix server/src
	uv run --package $(PACK_SDK) ruff check --config pyproject.toml --fix sdks/python/src

typecheck: engine-typecheck
	uv run --package $(PACK_MODELS) mypy --config-file pyproject.toml models/src
	uv run --package $(PACK_SERVER) mypy --config-file pyproject.toml server/src
	uv run --package $(PACK_SDK) mypy --config-file pyproject.toml sdks/python/src

# ---------------------------
# Build / Publish
# ---------------------------

build: build-models build-server build-sdk engine-build

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

engine-%:
	$(MAKE) -C $(ENGINE_DIR) $(patsubst engine-%,%,$@)

sdk-%:
	$(MAKE) -C $(SDK_DIR) $(patsubst sdk-%,%,$@)

.PHONY: server-%
server-%:
	$(MAKE) -C $(SERVER_DIR) $(patsubst server-%,%,$@)
