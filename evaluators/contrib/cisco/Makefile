.PHONY: help test lint lint-fix typecheck check build

PACKAGE := agent-control-evaluator-cisco

help:
	@echo "Agent Control Evaluator - Cisco AI Defense - Makefile commands"
	@echo "  make test       - run pytest"
	@echo "  make lint       - run ruff check"
	@echo "  make lint-fix   - run ruff check --fix"
	@echo "  make typecheck  - run mypy"
	@echo "  make check      - run test, lint, and typecheck"
	@echo "  make build      - build package"

test:
	uv run --with pytest --with pytest-asyncio --with pytest-cov --package $(PACKAGE) pytest tests --cov=src --cov-report=xml:../../../coverage-evaluators-cisco.xml -q

lint:
	uv run --with ruff --package $(PACKAGE) ruff check --config ../../../pyproject.toml src/

lint-fix:
	uv run --with ruff --package $(PACKAGE) ruff check --config ../../../pyproject.toml --fix src/

typecheck:
	uv run --with mypy --package $(PACKAGE) mypy --config-file ../../../pyproject.toml src/

check: test lint typecheck

build:
	uv build
