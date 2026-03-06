# Agent Control Examples

This directory contains runnable examples for the main Agent Control integration patterns.

Commands below assume you are starting from the repo root unless noted otherwise.

## Quick Start

1. Start the local Agent Control server:

```bash
make server-run
```

2. Set the server URL:

```bash
export AGENT_CONTROL_URL=http://localhost:8000
```

3. Set the model API key required by the example you want to run:
   - `GOOGLE_API_KEY` for Google ADK examples
   - `OPENAI_API_KEY` for LangChain, CrewAI, and steer-action examples
   - `GALILEO_API_KEY` for the Galileo Luna-2 example

## Recommended Starting Points

### Google ADK Callbacks (`google_adk_callbacks/`)

Canonical Google ADK integration using ADK callback hooks for model and tool checks.

```bash
cd examples/google_adk_callbacks
uv pip install -e . --upgrade
uv run python setup_controls.py
uv run adk run my_agent
```

### Google ADK Decorator (`google_adk_decorator/`)

Google ADK integration using Agent Control's `@control()` decorator for tool protection.

```bash
cd examples/google_adk_decorator
uv pip install -e . --upgrade
uv run python setup_controls.py
uv run adk run my_agent
```

Optional sdk-local execution for the decorator example:

```bash
cd examples/google_adk_decorator
uv run python setup_controls.py --execution sdk
uv run adk run my_agent
```

### Agent Control Demo (`agent_control_demo/`)

Small end-to-end demo of creating controls, running a protected agent, and updating controls dynamically.

```bash
uv run python examples/agent_control_demo/setup_controls.py
uv run python examples/agent_control_demo/demo_agent.py
uv run python examples/agent_control_demo/update_controls.py --allow-ssn
uv run python examples/agent_control_demo/update_controls.py --block-ssn
```

## Additional Examples

- [`customer_support_agent/README.md`](customer_support_agent/README.md): Rich customer-support workflow with protected tools and demo scripts.
- [`langchain/README.md`](langchain/README.md): LangChain examples for SQL tool protection and auto-derived step schemas.
- [`crewai/README.md`](crewai/README.md): CrewAI example combining Agent Control security checks with framework-level guardrails.
- [`steer_action_demo/README.md`](steer_action_demo/README.md): Banking transfer workflow showing `deny`, `warn`, and `steer` actions.
- [`deepeval/README.md`](deepeval/README.md): Custom evaluator authoring example using DeepEval GEval.
- [`galileo/README.md`](galileo/README.md): Luna-2 Protect integration example in [`galileo/luna2_demo.py`](galileo/luna2_demo.py).
- [`typescript_sdk/README.md`](typescript_sdk/README.md): Consumer-style TypeScript example using the published npm package.

## Notes

- Example-specific setup lives in each example directory README.
- The Google ADK callback example is server-only by design.
- The Google ADK decorator example includes the optional `execution="sdk"` setup path for local evaluation.
