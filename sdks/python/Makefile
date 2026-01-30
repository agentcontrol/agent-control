.PHONY: help test lint lint-fix typecheck build publish

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
	$(MAKE) -C ../../ server-alembic-upgrade
	@# Start server in background and save PID
	@uv run --package agent-control-server uvicorn agent_control_server.main:app --port 8000 --host 0.0.0.0 > server.log 2>&1 & echo $$! > server.pid
	@echo "Waiting for server..."
	@bash -c 'for i in {1..30}; do if curl -s http://localhost:8000/health >/dev/null; then echo "Server up!"; exit 0; fi; sleep 1; done; echo "Server failed"; cat server.log; exit 1'
	@# Run tests, capture exit code, and ensure cleanup
	@set -e; \
	uv run pytest --cov=src --cov-report=xml:../../coverage-sdk.xml -q; \
	TEST_EXIT_CODE=$$?; \
	echo "Stopping server..."; \
	if [ -f server.pid ]; then kill `cat server.pid` && rm server.pid; fi; \
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
