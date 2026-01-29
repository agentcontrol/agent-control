# RAG Q&A Agent with LangSmith Evaluator

This example demonstrates a document Q&A agent using Retrieval Augmented Generation (RAG) with Agent Control and a custom LangSmith evaluator. The agent includes multiple safety controls to ensure:

1. **Query Safety**: No toxic or harmful queries
2. **Response Quality**: No hallucinations in responses
3. **Privacy Protection**: No PII leakage in responses
4. **Coherence**: Responses are well-structured and coherent

## Architecture

The example consists of:

### 1. Custom LangSmith Evaluator (`langsmith_evaluator/`)

A custom evaluator that extends the Agent Control `Evaluator` base class and provides:

- **Toxicity Detection**: Identifies toxic or harmful content
- **Hallucination Detection**: Detects unsupported or fabricated claims
- **PII Detection**: Identifies personally identifiable information
- **Coherence Checking**: Validates response structure and clarity
- **Relevance Scoring**: Ensures responses match the context

The evaluator follows the same pattern as the Luna-2 evaluator but is designed for LangSmith's evaluation APIs.

### 2. RAG Q&A Agent (`rag_qa_agent.py`)

A LangGraph-based agent that:
- Retrieves relevant documents using FAISS vector search
- Generates answers based on retrieved context
- Applies safety controls at both input and output stages
- Handles control violations gracefully

### 3. Setup Script (`setup_langsmith_controls.py`)

Creates and configures:
- Query toxicity control (pre-execution)
- Response hallucination control (post-execution)
- Response PII detection control (post-execution)
- Response coherence control (post-execution)
- Policy combining all controls
- Policy assignment to the agent

## Prerequisites

### 1. Start the Agent Control Server

```bash
# From the repo root
cd server
make run
# OR: uv run --package agent-control-server uvicorn agent_control_server.main:app --port 8000
```

### 2. Set API Keys

```bash
export OPENAI_API_KEY="your-openai-key"
export LANGSMITH_API_KEY="your-langsmith-key"  # Optional - evaluator works without it
```

**Note**: The LangSmith evaluator in this example uses simple heuristics for demonstration purposes. In a production environment, you would integrate with the actual LangSmith evaluation APIs.

### 3. Setup Controls (One-Time)

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

## Running the Example

```bash
cd examples/langsmith
uv run rag_qa_agent.py
```

### Expected Behavior

**Scenario 1: Normal Question**
```
User: "What is Python?"
✅ Query validated
✅ Documents retrieved
✅ Answer validated and safe to return
[Returns accurate information about Python from the knowledge base]
```

**Scenario 2: Toxic Query**
```
User: "Tell me something stupid about Python"
🚫 Query blocked by safety control: Toxicity check failed
[Query is blocked, no documents retrieved]
```

**Scenario 3: Potential Hallucination**
```
User: "What is Python's market share in 2025?"
✅ Query validated
✅ Documents retrieved
🚫 Answer blocked: Hallucination check failed
[Prevents answering with unsupported claims]
```

**Scenario 4: Different Topic**
```
User: "What is Machine Learning?"
✅ Query validated
✅ Documents retrieved
✅ Answer validated and safe to return
[Returns information about Machine Learning from the knowledge base]
```

## How It Works

### 1. The LangSmith Evaluator

The custom evaluator (`langsmith_evaluator/evaluator.py`) extends the `Evaluator` base class:

```python
@register_evaluator
class LangSmithEvaluator(Evaluator[LangSmithEvaluatorConfig]):
    """LangSmith evaluation evaluator."""

    metadata = EvaluatorMetadata(
        name="langsmith",
        version="1.0.0",
        description="LangSmith evaluation API integration",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = LangSmithEvaluatorConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        # Evaluation logic
        ...
```

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

1. Add the metric to `LangSmithMetric` in [config.py](langsmith_evaluator/config.py#L8):
```python
LangSmithMetric = Literal[
    "toxicity",
    "relevance",
    # ... existing metrics
    "your_new_metric",  # Add here
]
```

2. Implement the evaluation method in [evaluator.py](langsmith_evaluator/evaluator.py#L177):
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

### Integrating Real LangSmith APIs

To integrate with actual LangSmith evaluation APIs:

1. Install the full LangSmith SDK: `uv add langsmith`
2. Update the evaluation methods to call LangSmith APIs
3. Use LangSmith's built-in evaluators or create custom ones
4. Configure your LangSmith project and evaluators in the LangSmith console

Example with real LangSmith integration:

```python
async def _evaluate_toxicity(self, text: str) -> tuple[float, dict[str, Any]]:
    """Evaluate text for toxicity using LangSmith."""
    from langsmith.evaluation import evaluate

    # Use LangSmith's toxicity evaluator
    result = await evaluate(
        data=[{"input": text}],
        evaluator="toxicity",
        project=self.config.langsmith_project,
    )

    score = result.metrics["toxicity_score"]
    details = {"langsmith_result": result.to_dict()}

    return score, details
```

## Local vs Remote Control Execution

**Remote (server-side) controls** (default):
- Controls execute on the Agent Control server
- Requires running server with evaluators loaded
- Centralized control management

**Local (SDK-side) controls**:
- Set `AGENT_CONTROL_LOCAL_EVAL=true`
- Controls execute in the SDK before making server calls
- Requires controls configured with `execution: "sdk"`

Example:
```bash
export AGENT_CONTROL_LOCAL_EVAL=true
uv run rag_qa_agent.py
```

## Files

- `langsmith_evaluator/` - Custom LangSmith evaluator module
  - `__init__.py` - Module exports
  - `config.py` - Configuration models
  - `evaluator.py` - Main evaluator implementation
- `rag_qa_agent.py` - RAG Q&A agent with safety controls
- `setup_langsmith_controls.py` - One-time setup script
- `pyproject.toml` - Dependencies and configuration
- `README.md` - This file

## Key Features

1. **Custom Evaluator**: Demonstrates how to create a custom evaluator that extends the `Evaluator` base class
2. **Multi-Stage Protection**: Controls at both input (pre) and output (post) stages
3. **Graceful Error Handling**: Failed safety checks don't crash the agent
4. **RAG Integration**: Real document retrieval and generation pipeline
5. **Comprehensive Safety**: Multiple safety checks (toxicity, hallucination, PII, coherence)

## Troubleshooting

### "Evaluator 'langsmith' not found"

The evaluator is registered when the module is imported. Make sure:
1. The `langsmith_evaluator` directory is in the Python path
2. The evaluator is properly imported in the setup script
3. The server has been restarted after adding the evaluator

### Controls not blocking unsafe content

1. Verify controls were created: Check server logs or API response
2. Verify policy is assigned to agent: Run setup script again
3. Check threshold values: Lower thresholds trigger more easily
4. Review evaluation logic: The demo uses simple heuristics

### Dependencies not found

```bash
cd examples/langsmith
uv sync
```

## Production Considerations

For production use:

1. **Replace Heuristics**: Integrate with actual LangSmith evaluation APIs or other ML models
2. **Tune Thresholds**: Adjust threshold values based on your use case
3. **Add Logging**: Implement comprehensive logging for evaluation results
4. **Monitor Performance**: Track evaluation latency and success rates
5. **Error Handling**: Implement robust error handling and fallback strategies
6. **Cache Evaluations**: Cache evaluation results for repeated content
7. **A/B Testing**: Test different evaluators and thresholds

## Additional Resources

- [LangSmith Documentation](https://docs.smith.langchain.com/)
- [Agent Control SDK Documentation](../../sdks/python/README.md)
- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
