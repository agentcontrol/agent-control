# DeepEval GEval Evaluator Example

This example demonstrates how to extend the agent-control `Evaluator` base class to create custom evaluators using external libraries like [DeepEval](https://deepeval.com).

## Overview

DeepEval's GEval is an LLM-as-a-judge metric that uses chain-of-thoughts (CoT) to evaluate LLM outputs based on custom criteria. This example shows how to:

1. **Extend the base Evaluator class** - Create a custom evaluator by implementing the required interface
2. **Configure evaluation criteria** - Define custom quality metrics (coherence, relevance, correctness, etc.)
3. **Register via entry points** - Make the evaluator discoverable by the agent-control server
4. **Integrate with agent-control** - Use the evaluator in controls to enforce quality standards

## Architecture

```
examples/deepeval/
├── __init__.py                      # Package initialization
├── config.py                        # DeepEvalEvaluatorConfig - Configuration model
├── evaluator.py                     # DeepEvalEvaluator - Main evaluator implementation
├── qa_agent.py                      # Q&A agent with DeepEval controls
├── setup_controls.py                # Setup script to create controls on server
├── start_server_with_evaluator.sh  # Helper script to start server with evaluator
├── pyproject.toml                   # Project config with entry point and dependencies
└── README.md                        # This file
```

**Package Structure Notes:**
- Uses a **flat layout** with Python files at the root (configured via `packages = ["."]` in pyproject.toml)
- Modules use **absolute imports** (e.g., `from config import X`) rather than relative imports
- Entry point `evaluator:DeepEvalEvaluator` references the module directly
- Install with `uv pip install -e .` to register the entry point for server discovery

### Key Components

1. **DeepEvalEvaluatorConfig** ([config.py](config.py))
   - Pydantic model defining configuration options
   - Based on DeepEval's GEval API parameters
   - Validates that either `criteria` or `evaluation_steps` is provided

2. **DeepEvalEvaluator** ([evaluator.py](evaluator.py))
   - Extends `Evaluator[DeepEvalEvaluatorConfig]`
   - Implements the `evaluate()` method
   - Registered with `@register_evaluator` decorator
   - Handles LLMTestCase creation and metric execution

3. **Q&A Agent Demo** ([qa_agent.py](qa_agent.py))
   - Complete working agent with DeepEval quality controls
   - Uses `@control()` decorator for automatic evaluation
   - Demonstrates handling `ControlViolationError`

4. **Setup Script** ([setup_controls.py](setup_controls.py))
   - Creates agent and registers with server
   - Configures DeepEval-based controls
   - Creates 3 quality controls (coherence, relevance, correctness)

5. **Entry Point Registration** ([pyproject.toml](pyproject.toml))
   - Registers evaluator with server via `project.entry-points`
   - Depends on `agent-control-evaluators>=5.0.0`, `agent-control-models>=5.0.0`, and `agent-control-sdk>=5.0.0`
   - In monorepo: uses workspace dependencies (editable installs)
   - For third-party: can use published PyPI packages
   - Enables automatic discovery when server starts

## How It Works

### 1. Extending the Evaluator Base Class

The evaluator follows the standard pattern for all agent-control evaluators:

```python
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator

@register_evaluator
class DeepEvalEvaluator(Evaluator[DeepEvalEvaluatorConfig]):
    # Define metadata
    metadata = EvaluatorMetadata(
        name="deepeval-geval",
        version="1.0.0",
        description="DeepEval GEval custom LLM-based evaluator",
        requires_api_key=True,
        timeout_ms=30000,
    )

    # Define config model
    config_model = DeepEvalEvaluatorConfig

    # Implement evaluate method
    async def evaluate(self, data: Any) -> EvaluatorResult:
        # matched=True triggers the deny action when quality fails
        # matched=False allows the request when quality passes
        return EvaluatorResult(
            matched=not is_successful,  # Trigger when quality fails
            confidence=score,
            message=reason,
        )
```

### 2. Entry Point Registration

The evaluator is registered via `pyproject.toml`:

```toml
[project]
dependencies = [
    "agent-control-evaluators>=5.0.0",
    "agent-control-models>=5.0.0",
    "agent-control-sdk>=5.0.0",
    "deepeval>=1.0.0",
    # ... other dependencies
]

[project.entry-points."agent_control.evaluators"]
deepeval-geval = "evaluator:DeepEvalEvaluator"
```

This makes the evaluator automatically discoverable by the server when it starts. The pattern works with both workspace dependencies (for monorepo development) and published PyPI packages (for third-party evaluators).

### 3. Configuration

DeepEval's GEval supports two modes:

**With Criteria** (auto-generates evaluation steps):
```python
config = DeepEvalEvaluatorConfig(
    name="Coherence",
    criteria="Evaluate whether the response is coherent and logically consistent.",
    evaluation_params=["input", "actual_output"],
    threshold=0.6,
)
```

**With Explicit Steps**:
```python
config = DeepEvalEvaluatorConfig(
    name="Correctness",
    evaluation_steps=[
        "Check whether facts in actual output contradict expected output",
        "Heavily penalize omission of critical details",
        "Minor wording differences are acceptable"
    ],
    evaluation_params=["input", "actual_output", "expected_output"],
    threshold=0.7,
)
```

### 4. Using in Control Definitions

Once registered, the evaluator can be used in control definitions:

```python
control_definition = {
    "name": "check-coherence",
    "description": "Ensures responses are coherent and logically consistent",
    "definition": {
        "description": "Ensures responses are coherent",
        "enabled": True,
        "execution": "server",
        "scope": {"stages": ["post"]},  # Apply to all steps at post stage
        "selector": {},  # Pass full data (input + output)
        "evaluator": {
            "name": "deepeval-geval",  # From metadata.name
            "config": {
                "name": "Coherence",
                "criteria": "Evaluate whether the response is coherent",
                "evaluation_params": ["input", "actual_output"],
                "threshold": 0.6,
                "model": "gpt-4o",
            },
        },
        "action": {
            "decision": "deny",
            "message": "Response failed coherence check",
        },
    },
}
```

**Key points:**
- `execution: "server"` - Required field
- `scope: {"stages": ["post"]}` - Apply to all function calls at post stage
- `selector: {}` - Pass full data so evaluator gets both input and output
- `evaluation_params: ["input", "actual_output"]` - Both fields required for relevance checks

## Getting Started from Fresh Clone

This example demonstrates **custom evaluator development** within the agent-control monorepo. It uses workspace dependencies (editable installs) to work with the latest development versions of:
- `agent-control-models` - Base evaluator classes and types
- `agent-control-sdk` - Agent Control SDK for integration
- `deepeval` - DeepEval evaluation framework

**Note:** This is a **development/monorepo example** showing the evaluator architecture.

### 1. Clone Repository

```bash
# Clone the repository
git clone https://github.com/agentcontrol/agent-control.git
cd agent-control
```

### 2. Start Database and Server

```bash
# Start PostgreSQL database and run migrations
cd server && docker-compose up -d && make alembic-upgrade && cd ..

# Start the agent-control server (from repository root)
make server-run
```

The server will be running at `http://localhost:8000`.

### 3. Install DeepEval Example

```bash
# Navigate to the DeepEval example directory
cd examples/deepeval

# Install dependencies
uv sync

# Install the evaluator package itself in editable mode
uv pip install -e .
```

This installs:
- **Dependencies**: `deepeval>=1.0.0`, `openai>=1.0.0`, `pydantic>=2.0.0`, etc.
- **Workspace packages** (as editable installs): `agent-control-models`, `agent-control-sdk`
- **This evaluator package** in editable mode, which registers the entry point for server discovery

The entry point `deepeval-geval = "evaluator:DeepEvalEvaluator"` makes the evaluator discoverable by the server.

### 4. Set Environment Variables

```bash
# Required for DeepEval GEval (uses OpenAI models)
export OPENAI_API_KEY="your-openai-api-key"

# Optional: Disable DeepEval telemetry
export DEEPEVAL_TELEMETRY_OPT_OUT="true"
```

### 5. Restart Server

After installing the DeepEval example, restart the server so it can discover the new evaluator:

```bash
# Stop the server (Ctrl+C) and restart
cd ../../  # Back to repository root
make server-run
```

Verify the evaluator is registered:
```bash
curl http://localhost:8000/api/v1/evaluators | grep deepeval-geval
```

### 6. Setup Agent and Controls

```bash
cd examples/deepeval
uv run setup_controls.py
```

This creates the agent registration and three quality controls (coherence, relevance, correctness).

### 7. Run the Q&A Agent

```bash
uv run qa_agent.py
```

Try asking questions like "What is Python?" or test the controls with "Tell me about something trigger_irrelevant".

---

## Testing the Agent

### Interactive Commands

Once the agent is running, try these commands:

```
You: What is Python?
You: What is the capital of France?
You: Test trigger_incoherent response please
You: Tell me about something trigger_irrelevant
You: /test-good       # Test with quality questions
You: /test-bad        # Test quality control triggers
You: /help            # Show all commands
You: /quit            # Exit
```

The agent will:
- Accept questions with coherent, relevant responses
- Block questions that produce incoherent or irrelevant responses
- Show which control triggered when quality checks fail

### What to Expect

**Good Quality Responses** (Pass controls):
```
You: What is Python?
Agent: Python is a high-level, interpreted programming language known for its
       simplicity and readability. It was created by Guido van Rossum and first
       released in 1991. Python supports multiple programming paradigms...
```

**Poor Quality Responses** (Blocked by controls):
```
You: Test trigger_incoherent response please
⚠️  Quality control triggered: check-coherence
    Reason: Response failed coherence check

Agent: I apologize, but my response didn't meet quality standards.
       Could you rephrase your question or ask something else?
```

The DeepEval controls evaluate responses in real-time and block those that don't meet quality thresholds.

## Evaluation Parameters

DeepEval supports multiple test case parameters:

- `input` - The user query or prompt
- `actual_output` - The LLM's generated response
- `expected_output` - Reference/ground truth answer
- `context` - Additional context for evaluation
- `retrieval_context` - Retrieved documents (for RAG)
- `tools_called` - Tools invoked by the agent
- `expected_tools` - Expected tool usage
- Plus MCP-related parameters

Configure which parameters to use via the `evaluation_params` config field.

**Important:** For relevance checks, always include both `input` and `actual_output` so the evaluator can compare the question with the answer.

## For Third-Party Developers

This example shows the **evaluator architecture** for extending agent-control. While this specific example is set up for monorepo development, the same pattern works for third-party evluators using published packages.

To create your own evaluator:

1. **Extend the Evaluator base class** from `agent-control-evaluators` (published on PyPI)
2. **Define a configuration model** using Pydantic
3. **Register via entry points** in your `pyproject.toml`
4. **Install your package** so the server can discover the entry point
5. **Restart the server** to load the new evaluator

For standalone packages outside the monorepo, use published versions:
```toml
[project]
dependencies = [
    "agent-control-evaluators>=5.0.0",  # From PyPI - base classes
    "agent-control-models>=5.0.0",       # From PyPI - data models
    "your-evaluation-library>=1.0.0"
]
```

See the [Extending This Example](#extending-this-example) section below for the complete pattern.

### Production Deployment

For production deployments, build your evaluator as a Python wheel and install it on your agent-control server:

**Development (this example):**
```bash
uv pip install -e .  # Editable install for development
```

**Production:**
```bash
python -m build      # Creates dist/*.whl
# Install wheel on production server where agent-control runs
```

**Deployment Options:**

1. **Self-Hosted Server (Full Control)**
   - Deploy your own agent-control server instance
   - Install custom evaluator packages (wheel, source, or private PyPI)
   - Your agents connect to this server via the SDK
   - Complete control over evaluators and controls

2. **Managed Service (If Available)**
   - Use a hosted agent-control service
   - May require coordination to install custom evaluators
   - Or use only built-in/approved evaluators

In both cases, evaluators run **server-side** (`execution: "server"`), so your agent applications only need the lightweight SDK installed. The evaluator package must be installed where the agent-control server runs, not in your agent application.

## Extending This Example

### Creating Your Own Custom Evaluator

Follow this pattern to create evaluators for other libraries:

1. **Define a Config Model**
   ```python
   from pydantic import BaseModel

   class MyEvaluatorConfig(BaseModel):
       threshold: float = 0.5
       # Your config fields
   ```

2. **Implement the Evaluator**
   ```python
   from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator

   @register_evaluator
   class MyEvaluator(Evaluator[MyEvaluatorConfig]):
       metadata = EvaluatorMetadata(name="my-evaluator", ...)
       config_model = MyEvaluatorConfig

       async def evaluate(self, data: Any) -> EvaluatorResult:
           score = # Your evaluation logic
           return EvaluatorResult(
               matched=score < self.config.threshold,  # Trigger when fails
               confidence=score,
           )
   ```

3. **Register via Entry Point**
   ```toml
   [project.entry-points."agent_control.evaluators"]
   my-evaluator = "evaluator:MyEvaluator"
   ```

4. **Install and Use**
   ```bash
   uv sync  # Server will discover it automatically
   ```

### Adding More GEval Metrics

You can create specialized evaluators for specific use cases:

- **Bias Detection**: Evaluate responses for bias or fairness
- **Safety**: Check for harmful or unsafe content
- **Style Compliance**: Ensure responses match brand guidelines
- **Technical Accuracy**: Validate technical correctness
- **Tone Assessment**: Evaluate emotional tone and sentiment

## Resources

- **DeepEval Documentation**: https://deepeval.com/docs/metrics-llm-evals
- **G-Eval Guide**: https://www.confident-ai.com/blog/g-eval-the-definitive-guide
- **Agent Control Evaluators**: [Base evaluator class](../../evaluators/builtin/src/agent_control_evaluators/_base.py)
- **CrewAI Example**: [Using agent-control as a consumer](../crewai/)

## Key Takeaways

1. **Entry Points are Critical**: The server discovers evaluators via `project.entry-points`, not PYTHONPATH
2. **Extensibility**: The `Evaluator` base class makes it easy to integrate any evaluation library
3. **Configuration**: Pydantic models provide type-safe, validated configuration
4. **Registration**: The `@register_evaluator` decorator handles registration automatically
5. **Integration**: Evaluators work seamlessly with agent-control's control system
6. **Control Logic**: `matched=True` triggers the action (deny/allow), so invert when quality passes

## Troubleshooting

### Controls not triggering

- Check that `execution: "server"` is in control definition
- Use `scope: {"stages": ["post"]}` instead of `step_types`
- Use empty selector `{}` to pass full data (input + output)
- Restart server after evaluator code changes

### Evaluator not found

The server couldn't discover the evaluator. Check:

1. **Entry point registration** in `pyproject.toml`:
   ```toml
   [project.entry-points."agent_control.evaluators"]
   deepeval-geval = "evaluator:DeepEvalEvaluator"
   ```

2. **Package is installed**:
   ```bash
   cd examples/deepeval
   uv sync                  # Install dependencies
   uv pip install -e .      # Install this package
   ```

3. **Server was restarted** after package installation:
   ```bash
   # Stop server (Ctrl+C), then restart
   make server-run
   ```

4. **Verify registration**:
   ```bash
   curl http://localhost:8000/api/v1/evaluators | grep deepeval-geval
   ```

5. **Check server logs** for evaluator discovery messages during startup

### Wrong evaluation results

- For relevance: include both `input` and `actual_output` in `evaluation_params`
- Check that `matched` logic is inverted (trigger when quality fails)
- Lower threshold to be more strict (0.5 instead of 0.7)

### Import errors: "cannot import name 'X'"

If you see import errors like `ImportError: cannot import name 'AgentRef'`:

1. **Stale editable install**: Reinstall the package
   ```bash
   uv pip install -e /path/to/package --force-reinstall --no-deps
   ```

2. **For agent-control-models specifically**:
   ```bash
   uv pip install -e ../../models --force-reinstall --no-deps
   ```

3. **Clear Python cache** if issues persist:
   ```bash
   find . -name "*.pyc" -delete
   find . -name "__pycache__" -type d -exec rm -rf {} +
   ```

4. **Verify installation**:
   ```bash
   python -c "from agent_control_models.server import AgentRef; print('Success')"
   ```

### Package not discoverable: "attempted relative import"

If you see `attempted relative import with no known parent package`:

1. **Ensure the package is installed**:
   ```bash
   cd examples/deepeval
   uv pip install -e .
   ```

2. **Verify entry point registration**:
   ```bash
   uv pip show agent-control-deepeval-example
   ```

3. **Check pyproject.toml has**:
   ```toml
   [tool.hatch.build.targets.wheel]
   packages = ["."]
   ```

### DeepEval telemetry files

- DeepEval creates a `.deepeval/` directory with telemetry files in the working directory
- When the evaluator runs on the server, files appear in `server/.deepeval/`
- These files don't need to be committed (add `.deepeval/` to `.gitignore`)
- To disable telemetry: set environment variable `DEEPEVAL_TELEMETRY_OPT_OUT="true"`

## License

This example is part of the agent-control project.
