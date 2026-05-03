.PHONY: help sync test lint lint-fix typecheck check build publish

PACKAGE := agent-control-evaluator-galileo

help:
	@echo "Agent Control Evaluator - Galileo - Makefile commands"
	@echo ""
	@echo "  make test            - run pytest"
	@echo "  make lint            - run ruff check"
	@echo "  make lint-fix        - run ruff check --fix"
	@echo "  make typecheck       - run mypy"
	@echo "  make check           - run test, lint, and typecheck"
	@echo "  make build           - build package"

sync:
	uv sync

test:
	uv run --with pytest --with pytest-asyncio --with pytest-cov --package $(PACKAGE) pytest tests --cov=src --cov-report=xml:../../../coverage-evaluators-galileo.xml -q

lint:
	uv run --with ruff --package $(PACKAGE) ruff check --config ../../../pyproject.toml src/

lint-fix:
	uv run --with ruff --package $(PACKAGE) ruff check --config ../../../pyproject.toml --fix src/

typecheck:
	uv run --with mypy --package $(PACKAGE) mypy --config-file ../../../pyproject.toml src/

check: test lint typecheck

build:
	uv build

publish:
	uv publish
