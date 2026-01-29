# LangSmith Integration with Agent Control

This example demonstrates how to integrate Agent Control with existing LangSmith workflows using a custom LangSmith evaluator. It shows how applications already using LangSmith for observability can add runtime safety controls without changing their existing architecture.

The example includes multiple safety controls to ensure:

1. **Query Safety**: Block toxic or harmful queries before processing
2. **Response Quality**: Prevent hallucinations in generated responses
3. **Privacy Protection**: Detect and block PII leakage in responses
4. **Coherence**: Ensure responses are well-structured and coherent

## Architecture

The example consists of:

### 1. Custom LangSmith Evaluator

A custom evaluator (`evaluator.py`) that extends the Agent Control `Evaluator` base class and integrates with LangSmith:

- **LLM-as-Judge Pattern**: Uses OpenAI GPT-4 to evaluate content quality
- **LangSmith Tracing**: All evaluations are traced in LangSmith for observability
- **Multiple Metrics**: Toxicity, hallucination detection, PII detection, coherence, relevance, accuracy
- **Fallback Heuristics**: Simple heuristics when API is unavailable

The evaluator seamlessly integrates Agent Control's runtime enforcement with LangSmith's observability.

### 2. Setup Script (`setup_langsmith_controls.py`)

Creates and configures:
- Query toxicity control (pre-execution)
- Response hallucination control (post-execution)
- Response PII detection control (post-execution)
- Response coherence control (post-execution)
- Policy combining all controls
- Policy assignment to the agent

### 3. Integration Demo (`langsmith_api_integration_demo.py`)

Comprehensive demonstration showing:
- Direct LangSmith client usage with LLM-as-judge
- RAG Q&A agent with real-time safety controls
- Metric comparison across different evaluation types
- Integration with existing LangChain/LangGraph workflows

## Prerequisites and Installation

**IMPORTANT: Follow these steps in order!**

### Step 1: Install the LangSmith Example Package

The LangSmith evaluator needs to be installed and registered before starting the server.

```bash
# From the repo root
cd examples/langsmith

# Install the package in editable mode (includes evaluator and all dependencies)
uv pip install -e .
# OR: pip install -e .
```

This installs:
- All required dependencies (langchain, faiss, httpx, etc.)
- The agent-control SDK and models
- The LangSmith evaluator (registered via Python entry points)

### Step 2: Restart the Agent Control Server

**CRITICAL: The server MUST be restarted after installing the evaluator!**

The server discovers evaluators on startup via entry points. If the server is already running, it won't know about the new evaluator.

```bash
# Kill any existing server instances
pkill -f "uvicorn agent_control_server"

# Start the server (from repo root)
cd server
make run
# OR: uv run --package agent-control-server uvicorn agent_control_server.main:app --port 8000
```

**Verify the evaluator is loaded** by checking the server logs for:
```
INFO: Registered evaluator: langsmith (v1.0.0)
```

If you **don't see this message**, the evaluator was not discovered. Check:
- Did you install the package in Step 1?
- Did you restart (not just start) the server?

### Step 3: Set API Keys

```bash
export OPENAI_API_KEY="your-openai-key"        # Required for LLM-as-judge evaluations
```

**Optional - LangSmith Tracing (Privacy Warning)**:
```bash
export LANGSMITH_API_KEY="your-langsmith-key"  # Enables tracing to LangSmith servers
```

**Privacy Note**:
- **Without LANGSMITH_API_KEY**: Evaluations run locally using OpenAI. Only OpenAI sees your data.
- **With LANGSMITH_API_KEY**: Evaluation data (prompts, responses, metadata) is sent to LangSmith's servers for tracing and observability.

If you want to keep your Agent Control implementation private, **do not set LANGSMITH_API_KEY**. The evaluations will work perfectly without it.

### Step 4: Setup Controls (One-Time)

Now create the controls that will use the LangSmith evaluator:

```bash
cd examples/langsmith
uv run setup_langsmith_controls.py
```

This creates:
- Query toxicity control (blocks harmful queries)
- Response hallucination control (prevents fabricated information)
- Response PII control (prevents personal data leakage)
- Response coherence control (ensures well-structured responses)
- Policy with all controls assigned to the RAG agent

**Common Error**: If you get a **422 error**, the server doesn't recognize the "langsmith" evaluator. Go back to Step 2 and restart the server.

## Running the Example

Run the comprehensive integration demo that shows how Agent Control integrates with LangSmith workflows:

```bash
cd examples/langsmith
export OPENAI_API_KEY="your-openai-key"
export LANGSMITH_API_KEY="your-langsmith-key"
uv run langsmith_api_integration_demo.py
```

The demo includes three parts:

1. **Demo 1: Basic LangSmith Client** - Direct evaluation API usage
2. **Demo 2: RAG Agent with Controls** - Full integration with LangGraph/LangChain
3. **Demo 3: Metric Comparison** - Compare different evaluation metrics

### Expected Behavior (Demo 2)

**Scenario 1: Safe Query**
```
Query: "What is Python?"
✅ Pre-Control: Toxicity check passed
✅ Action: Retrieved documents
✅ Post-Control: Hallucination and PII checks passed
📝 Answer: [Returns accurate information about Python]
```

**Scenario 2: Toxic Query**
```
Query: "I hate this stupid programming language..."
❌ Pre-Control: BLOCKED by toxicity check
🛡️ Reason: High toxicity score
📊 Control: Toxicity Check (Pre-execution)
```

**Scenario 3: Query with PII**
```
Query: "Tell me about Python. My email is john@example.com"
✅ Pre-Control: Toxicity check passed (query may be safe)
✅ Action: Retrieved documents
❌ Post-Control: BLOCKED by PII detection
🛡️ Reason: Response contains email address
📊 Control: PII Detection (Post-execution)
```

## How It Works

### 1. The LangSmith Evaluator

The custom evaluator (`evaluator.py`) extends the `Evaluator` base class and uses the LLM-as-judge pattern:

```python
@register_evaluator
class LangSmithEvaluator(Evaluator[LangSmithEvaluatorConfig]):
    """LangSmith evaluation evaluator using LLM-as-judge pattern."""

    metadata = EvaluatorMetadata(
        name="langsmith",
        version="1.0.0",
        description="LangSmith LLM-as-judge evaluation",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = LangSmithEvaluatorConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        # Extract text and context
        text, context = self._extract_text_and_context(data)

        # Call OpenAI GPT-4 as judge (traced in LangSmith)
        client = self._get_client()
        response = await client.evaluate(
            text=text,
            metric=self.config.metric,
            context=context,
            project_name=self.config.langsmith_project,
        )

        # Return result based on threshold
        score = response.metrics.score
        matched = score > self.config.threshold
        return EvaluatorResult(matched=matched, confidence=score, ...)
```

The evaluator uses OpenAI's GPT-4 to judge content quality. Each evaluation is traced in LangSmith for observability.

### 2. Evaluation Flow

```
User Query → @control() decorator → Toxicity Check
                                          ↓
                                    [DENY/ALLOW]
                                          ↓
                                  Vector Search
                                          ↓
                                  Generate Answer
                                          ↓
                           @control() decorator → Hallucination Check
                                                  PII Check
                                                  Coherence Check
                                                       ↓
                                                 [DENY/ALLOW]
                                                       ↓
                                                 Return to User
```

### 3. Control Configuration

Each control specifies:
- **Stage**: `pre` (before execution) or `post` (after execution)
- **Step Type Filter**: Which step types to evaluate (e.g., `tool`)
- **Tool Name Filter**: Which tools to evaluate (e.g., `retrieve_documents`, `generate_answer`)
- **Evaluator Config**: LangSmith evaluator configuration with metric and threshold
- **Selector**: Which part of the data to evaluate (e.g., `input.query`, `output`)
- **Action**: What to do if control triggers (e.g., `deny`)

Example control configuration:

```python
{
    "name": "query-toxicity-check",
    "data": {
        "description": "Block toxic or harmful queries",
        "stage": "pre",
        "execution": "server",
        "step_type_filter": ["tool"],
        "tool_name_filter": ["retrieve_documents"],
        "evaluator_configs": [
            {
                "evaluator": "langsmith",
                "config": {
                    "metric": "toxicity",
                    "threshold": 0.6,
                    "langsmith_project": "agent-control-demo",
                },
                "selector": "input.query",
                "action": "deny",
            }
        ],
    },
}
```

## Customization

### Adding New Metrics

To add a new evaluation metric to the LangSmith evaluator:

1. Add the metric to `LangSmithMetric` in [config.py](config.py#L8):
```python
LangSmithMetric = Literal[
    "toxicity",
    "relevance",
    # ... existing metrics
    "your_new_metric",  # Add here
]
```

2. Implement the evaluation method in [evaluator.py](evaluator.py#L177):
```python
async def _evaluate_your_new_metric(
    self, text: str, context: str | None
) -> tuple[float, dict[str, Any]]:
    """Evaluate your new metric."""
    # Your evaluation logic here
    score = ...  # 0.0 to 1.0
    details = {...}
    return score, details
```

3. Add the case to `_evaluate_metric`:
```python
elif metric == "your_new_metric":
    return await self._evaluate_your_new_metric(text, context)
```

### LLM-as-Judge Pattern

**The evaluator now uses real LangSmith APIs with the LLM-as-judge pattern!**

The implementation (`client.py` and `evaluator.py`) uses:

1. **OpenAI GPT-4 as the Judge**: Evaluates content quality using natural language understanding
2. **LangSmith Tracing**: All evaluations are traced in LangSmith for observability
3. **Structured Prompts**: Each metric has a carefully crafted prompt for accurate evaluation
4. **Fallback Heuristics**: Simple heuristics used when API is unavailable

Example of LLM-as-judge evaluation:

```python
from client import LangSmithClient

# Initialize client
client = LangSmithClient(project_name="my-project")

# Evaluate toxicity using GPT-4 as judge
response = await client.evaluate(
    text="Your text here",
    metric="toxicity",
)

print(f"Score: {response.metrics.score}")
print(f"Reasoning: {response.metrics.details['reasoning']}")
```

The evaluation flow:
1. Create metric-specific prompt (e.g., "Evaluate this text for toxic content...")
2. Call OpenAI GPT-4 with the prompt
3. Trace the request in LangSmith
4. Parse LLM response (score + reasoning)
5. Return structured evaluation result

## Demo Details

### Demo 1: Basic LangSmith Client Usage
Direct usage of `LangSmithClient` for evaluations showing how the LLM-as-judge pattern works:
- Toxicity detection on clean vs toxic text
- Hallucination detection comparing output to context
- PII detection in text
- Each evaluation uses GPT-4 as judge with LangSmith tracing

### Demo 2: RAG Q&A Agent with Agent Control
**This is the main demo** showing how to integrate Agent Control with existing LangChain/LangGraph workflows:
- Vector search with FAISS (standard RAG pattern)
- GPT-4 answer generation (standard LangChain pattern)
- Real-time safety controls added via `@control()` decorator
- Agent Control enforcement with deny actions
- Graceful handling when controls trigger
- 5 interactive test scenarios showing safe and unsafe queries

**Key Integration Points:**
- Minimal code changes - just add `@control()` decorators
- Works with existing LangChain tools and chains
- All evaluations traced in LangSmith for observability
- Controls enforced before/after tool execution

### Demo 3: Metric Comparison
Evaluates the same text using multiple metrics side-by-side:
- Compare toxicity, coherence, and PII detection
- Shows how different metrics assess the same content
- Demonstrates LLM reasoning for each metric

**Requirements:**
- `OPENAI_API_KEY`: Required for LLM-as-judge evaluations
- `LANGSMITH_API_KEY`: Optional - enables tracing (WARNING: sends data to LangSmith servers)

## Files

- `__init__.py` - Package exports
- `config.py` - Evaluator configuration models with all supported metrics
- `evaluator.py` - Main LangSmith evaluator implementation (LLM-as-judge with fallbacks)
- `client.py` - LangSmith client using OpenAI GPT-4 for evaluations with tracing
- `setup_langsmith_controls.py` - One-time setup script to create controls and policies
- `langsmith_api_integration_demo.py` - Comprehensive demo showing LangSmith + Agent Control integration
- `pyproject.toml` - Package configuration with evaluator entry point and dependencies
- `README.md` - This file

## Key Features

1. **LangSmith Integration**: Shows how to add Agent Control to existing LangSmith workflows
2. **Custom Evaluator**: Demonstrates creating a custom evaluator that extends the `Evaluator` base class
3. **LLM-as-Judge**: Uses OpenAI GPT-4 for intelligent, context-aware evaluations
4. **Multi-Stage Protection**: Controls at both input (pre) and output (post) stages
5. **Minimal Code Changes**: Add safety controls with simple `@control()` decorators
6. **Full Observability**: All evaluations traced in LangSmith for monitoring and analysis
7. **Graceful Error Handling**: Fallback heuristics when API is unavailable
8. **Comprehensive Safety**: Multiple metrics (toxicity, hallucination, PII, coherence, relevance, accuracy)

## Troubleshooting

### Error: "422 Unprocessable Entity" when creating controls

**Cause**: The server doesn't recognize the "langsmith" evaluator.

**Solution**:
1. Make sure you completed Step 1 (install the package)
2. **Restart the server** (Step 2) - this is the most common fix!
3. Check server logs for `INFO: Registered evaluator: langsmith (v1.0.0)`
4. If the message is not there, the evaluator wasn't discovered

### Error: "Evaluator 'langsmith' not found"

**Cause**: The evaluator package wasn't installed correctly.

**Solution**:
1. Run `uv pip install -e .` from the `examples/langsmith` directory
2. Restart the server
3. Verify the entry point is correct in [pyproject.toml](pyproject.toml:26-27)

### Controls not blocking unsafe content

**Possible causes**:
1. Controls weren't created successfully - check setup script output
2. Policy not assigned to agent - run setup script again
3. Threshold values too high - lower thresholds trigger more easily
4. Evaluation logic needs tuning - the demo uses simple heuristics

### Dependencies not found

```bash
cd examples/langsmith
uv pip install -e .
```

### Server won't start or can't find evaluators

```bash
# Make sure you're in the right directory
cd server

# Check what evaluators are installed
pip list | grep agent-control

# Verify the langsmith example is installed
pip show langsmith-rag-example
```

## Production Considerations

For production use:

1. **Cost Management**: LLM-as-judge calls OpenAI API - monitor costs and consider caching
2. **Tune Thresholds**: Adjust threshold values based on your use case and evaluation data
3. **Model Selection**: Consider using `gpt-4-turbo` or `gpt-3.5-turbo` for cost/latency tradeoffs
4. **Monitor Performance**: Track evaluation latency, API costs, and success rates in LangSmith
5. **Error Handling**: The evaluator includes fallback heuristics when API is unavailable
6. **Cache Evaluations**: Cache evaluation results for repeated content to reduce API calls
7. **Rate Limiting**: Implement rate limiting for LLM-as-judge calls
8. **Custom Prompts**: Customize evaluation prompts in `client.py` for your specific use case

## Additional Resources

- [LangSmith Documentation](https://docs.smith.langchain.com/)
- [Agent Control SDK Documentation](../../sdks/python/README.md)
- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
