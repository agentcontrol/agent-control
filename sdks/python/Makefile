.PHONY: help test lint lint-fix typecheck build publish

TEST_DB ?= agent_control_test
TEST_SERVER_PORT ?= 18000
TEST_SERVER_HOST ?= 127.0.0.1
TEST_SERVER_URL := http://$(TEST_SERVER_HOST):$(TEST_SERVER_PORT)
TEST_DB_ENV := env -u AGENT_CONTROL_DB_URL -u DATABASE_URL -u DB_URL AGENT_CONTROL_DB_HOST=localhost AGENT_CONTROL_DB_PORT=5432 AGENT_CONTROL_DB_USER=agent_control AGENT_CONTROL_DB_PASSWORD=agent_control AGENT_CONTROL_DB_DATABASE=$(TEST_DB) AGENT_CONTROL_DB_DRIVER=psycopg

help:
	@echo "Agent Control SDK - Makefile commands"
	@echo ""
	@echo "Quality:"
	@echo "  make lint            - run ruff check (using root config)"
	@echo "  make lint-fix        - run ruff check --fix"
	@echo "  make typecheck       - run mypy (using root config)"
	@echo ""
	@echo "Test:"
	@echo "  make test            - run pytest"
	@echo ""
	@echo "Build:"
	@echo "  make build           - build package"
	@echo "  make publish         - publish package"

test:
	@echo "Starting server for tests..."
	$(TEST_DB_ENV) uv run --package agent-control-server python scripts/reset_test_db.py
	$(TEST_DB_ENV) $(MAKE) -C ../../ server-alembic-upgrade
	@# Start server in background and save PID
	@$(TEST_DB_ENV) uv run --package agent-control-server uvicorn agent_control_server.main:app --port $(TEST_SERVER_PORT) --host $(TEST_SERVER_HOST) > server.log 2>&1 & echo $$! > server.pid
	@echo "Waiting for server..."
	@bash -c 'for i in {1..30}; do if curl -s $(TEST_SERVER_URL)/health >/dev/null; then echo "Server up!"; exit 0; fi; sleep 1; done; echo "Server failed"; cat server.log; exit 1'
	@# Run tests, capture exit code, and ensure cleanup
	@TEST_EXIT_CODE=0; \
	$(TEST_DB_ENV) AGENT_CONTROL_TEST_URL=$(TEST_SERVER_URL) AGENT_CONTROL_URL=$(TEST_SERVER_URL) uv run pytest --cov=src --cov-report=xml:../../coverage-sdk.xml -q || TEST_EXIT_CODE=$$?; \
	echo "Stopping server..."; \
	if [ -f server.pid ]; then kill `cat server.pid` 2>/dev/null || true; rm -f server.pid; fi; \
	exit $$TEST_EXIT_CODE

lint:
	uv run ruff check --config ../../pyproject.toml src/

lint-fix:
	uv run ruff check --config ../../pyproject.toml --fix src/

typecheck:
	uv run mypy --config-file ../../pyproject.toml src/

build:
	uv build

publish:
	uv publish
