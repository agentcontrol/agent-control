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
# From repo root
make server-run
```

2. Install the example dependencies:

```bash
# In separate shell
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

For more details on this example, see the [Docs](https://docs.agentcontrol.dev/examples/google-adk-decorator).

> **Tip:** If you want the framework-native, attach-once ADK integration, use
> [`examples/google_adk_plugin/`](../google_adk_plugin/) instead.
