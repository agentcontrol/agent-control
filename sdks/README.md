# Agent Control SDKs

This workspace contains all SDK implementations for Agent Control.

## Available SDKs

- **Python SDK** (`python/`) - Python client for interacting with Agent Control services
- **TypeScript SDK** (`typescript/`) - Speakeasy-generated client plus TypeScript wrapper scaffold

## Development

This is a uv workspace. To work with the SDKs:

```bash
# From the sdks/ directory
cd sdks/

# Install dependencies
uv sync

# Run tests
uv run pytest

# Run linting
uv run ruff check .

# Run type checking
uv run mypy .
```

## Adding New SDKs

To add a new SDK (e.g., TypeScript, Go):
1. Create a new directory for the SDK
2. Add it to the `members` list in `sdks/pyproject.toml`
3. Ensure it references the models package if needed
