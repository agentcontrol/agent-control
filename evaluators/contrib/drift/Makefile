.PHONY: help sync test lint lint-fix typecheck build

PACKAGE := agent-control-evaluator-drift

help:
	@echo "Agent Control Evaluator - Drift - Makefile commands"
	@echo ""
	@echo "  make test            - run pytest"
	@echo "  make lint            - run ruff check"
	@echo "  make lint-fix        - run ruff check --fix"
	@echo "  make typecheck       - run mypy"
	@echo "  make build           - build package"

sync:
	uv sync

test:
	uv run pytest --cov=src --cov-report=xml:../../../coverage-evaluators-drift.xml -q

lint:
	uv run ruff check --config ../../../pyproject.toml src/

lint-fix:
	uv run ruff check --config ../../../pyproject.toml --fix src/

typecheck:
	uv run mypy --config-file ../../../pyproject.toml src/

build:
	uv build
