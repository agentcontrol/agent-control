# DeepEval Example

Custom evaluator using DeepEval GEval metrics for quality controls.

## What this example shows

- GEval-based quality checks
- SDK evaluation flow and error handling
- Control setup for quality enforcement

## Quick run

```bash
# From repo root
export OPENAI_API_KEY="your-key-here"
make server-run

# In a separate shell
cd examples/deepeval
uv pip install -e . --upgrade
uv run python setup_controls.py
uv run python qa_agent.py
```

Full walkthrough: https://docs.agentcontrol.dev/examples/deepeval
