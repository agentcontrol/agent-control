# DeepEval Example

Custom evaluator using DeepEval GEval metrics for quality controls.

## Quick run

```bash
# From repo root
make server-run
export OPENAI_API_KEY="your-key-here"

cd examples/deepeval
uv run pip install -e . --upgrade
uv run python setup_controls.py
uv run python qa_agent.py
```

Full walkthrough: [DeepEval Example](https://docs.agentcontrol.dev/examples/deepeval)
