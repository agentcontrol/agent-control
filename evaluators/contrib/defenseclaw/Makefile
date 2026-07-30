.PHONY: help sync test lint lint-fix typecheck check build

PACKAGE := agent-control-evaluator-defenseclaw

help:
	@echo "Agent Control Evaluator - DefenseClaw - Makefile commands"
	@echo "  make sync       - sync package dependencies"
	@echo "  make test       - run pytest"
	@echo "  make lint       - run ruff check"
	@echo "  make lint-fix   - run ruff check --fix"
	@echo "  make typecheck  - run mypy"
	@echo "  make check      - run tests, lint, and typecheck"
	@echo "  make build      - build package"

sync:
	uv sync

test:
	uv run --with pytest --with pytest-asyncio --with pytest-cov --package $(PACKAGE) pytest tests --cov=src --cov-report=xml:../../../coverage-evaluators-defenseclaw.xml -q

lint:
	uv run --with ruff --package $(PACKAGE) ruff check --config ../../../pyproject.toml src/ tests/

lint-fix:
	uv run --with ruff --package $(PACKAGE) ruff check --config ../../../pyproject.toml --fix src/ tests/

typecheck:
	uv run --with mypy --package $(PACKAGE) mypy --config-file ../../../pyproject.toml src/

check: test lint typecheck

build:
	uv build
