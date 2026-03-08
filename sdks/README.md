# Agent Control SDKs

This workspace contains all SDK implementations for Agent Control. Use these clients to register agents, manage controls, and evaluate requests from your application.

## Available SDKs

- **Python SDK** (`python/`) — Primary SDK with `@control()` decorator and async client APIs
- **TypeScript SDK** (`typescript/`) — Generated OpenAPI client plus TypeScript wrappers

## Quick links

- Python SDK docs: https://docs.agentcontrol.dev/sdk/python-sdk
- TypeScript SDK docs: https://docs.agentcontrol.dev/sdk/typescript-sdk

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

To add a new SDK (e.g., Go):
1. Create a new directory for the SDK
2. Add it to the `members` list in `sdks/pyproject.toml`
3. Ensure it references the models package if needed
