.PHONY: help test lint lint-fix typecheck check build

help:
	@echo "Agent Control Evaluator - Budget - Makefile commands"
	@echo ""
	@echo "  make test            - run pytest"
	@echo "  make lint            - run ruff check"
	@echo "  make lint-fix        - run ruff check --fix"
	@echo "  make typecheck       - run mypy"
	@echo "  make check           - run lint, typecheck, and test"
	@echo "  make build           - build package"

test:
	uv run --with pytest --with pytest-asyncio --with pytest-cov pytest tests --cov=src --cov-report=xml:../../../coverage-evaluators-budget.xml -q

lint:
	uv run --with ruff ruff check --config ../../../pyproject.toml src/

lint-fix:
	uv run --with ruff ruff check --config ../../../pyproject.toml --fix src/

typecheck:
	uv run --with mypy mypy --config-file ../../../pyproject.toml src/

check: lint typecheck test

build:
	uv build
