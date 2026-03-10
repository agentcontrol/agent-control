# Google ADK Decorator Example

This example shows how to use Agent Control's `@control()` decorator inside a
Google ADK app.

Use this example if you want ADK as the host framework but prefer Agent
Control's decorator model for tool protection.

## What It Demonstrates

- `@control()` on ADK tool functions
- automatic step registration from decorated functions
- pre-tool blocking for restricted cities
- post-tool output filtering for synthetic unsafe output
- optional sdk-local execution without changing the agent code

## Prerequisites

1. Start the Agent Control server from the repo root:

```bash
make server-run
```

2. Install the example dependencies:

```bash
cd examples/google_adk_decorator
uv pip install -e . --upgrade
```

3. Set your Google API key:

```bash
export GOOGLE_API_KEY="your-key-here"
```

4. Optional environment variables:

```bash
export AGENT_CONTROL_URL=http://localhost:8000
export GOOGLE_MODEL=gemini-2.5-flash
```

## Setup

Default server execution:

```bash
cd examples/google_adk_decorator
uv run python setup_controls.py
```

Optional sdk-local execution:

```bash
cd examples/google_adk_decorator
uv run python setup_controls.py --execution sdk
```

The example code does not change between modes. The only difference is where
the controls run:

- `server` - evaluation happens on the Agent Control server
- `sdk` - evaluation happens locally in the Python SDK after the controls are fetched

The setup script creates namespaced controls for this example:

- `adk-decorator-block-restricted-cities`
- `adk-decorator-block-internal-contact-output`

## Run

```bash
cd examples/google_adk_decorator
uv run adk run my_agent
```

## Suggested Scenarios

Safe request:

```text
What time is it in London?
```

Restricted city blocked before the tool call:

```text
What is the weather in Pyongyang?
```

Synthetic unsafe tool output blocked after the tool call:

```text
What time is it in Testville?
```

## Files

- `setup_controls.py` - creates the decorator example controls
- `my_agent/agent.py` - ADK app that wraps tools with `@control()`
- `.env.example` - environment variables for local runs

## Notes

- This example focuses on tool-level protection only.
- The guarded tool implementations are marked with tool metadata before
  `@control()` runs. That is needed because the current Python SDK infers
  `tool` vs `llm` from function metadata at decoration time.
- If you want the ADK-native callback integration pattern, use
  `examples/google_adk_callbacks/`.
