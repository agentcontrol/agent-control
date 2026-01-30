.PHONY: help sync test lint lint-fix typecheck build publish

# Package name
PACKAGE := agent-control-engine

help:
	@echo "Agent Control Engine - Makefile commands"
	@echo ""
	@echo "Setup:"
	@echo "  make sync            - uv sync dependencies"
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

sync:
	uv sync

test:
	uv run pytest --cov=src --cov-report=xml:../coverage-engine.xml -q

lint:
	uv run ruff check --config ../pyproject.toml src/

lint-fix:
	uv run ruff check --config ../pyproject.toml --fix src/

typecheck:
	uv run mypy --config-file ../pyproject.toml src/

build:
	uv build

publish:
	uv publish
