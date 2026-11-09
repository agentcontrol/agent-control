.PHONY: sync test lint lint-fix typecheck check build example

sync:
	uv sync

test:
	uv run pytest tests --cov=src --cov-report=xml:../../../coverage-evaluators-quarry.xml -q

lint:
	uv run ruff check --config ../../../pyproject.toml src/ tests/ examples/

lint-fix:
	uv run ruff check --config ../../../pyproject.toml --fix src/ tests/ examples/

typecheck:
	uv run mypy --config-file ../../../pyproject.toml src/

check: test lint typecheck

build:
	uv build

example:
	uv run python examples/local_policy.py
