.PHONY: sync test lint typecheck check build

sync:
	uv sync --group dev

test:
	uv run --group dev pytest --cov=src --cov-report=xml:../../../coverage-evaluators-detect-secrets.xml -q

lint:
	uv run --group dev ruff check .
	uv run --group dev ruff format --check .

typecheck:
	uv run --group dev mypy .

check: sync lint typecheck test build

build:
	uv build
