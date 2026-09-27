# Agent Control - Python SDK

Python SDK for adding safety controls and guardrails to AI agents. Protect tools and LLM calls with server-side or local policy enforcement.

## Installation

```bash
pip install agent-control-sdk
```

## Quick Start

```python
import agent_control
from agent_control import control

# Initialize
agent_control.init(agent_name="my-agent")

# Protect a tool with decorator
@control()
async def search_database(query: str) -> str:
    return db.execute(query)
```

Controls are defined centrally and enforced automatically at runtime. See [Python SDK Documentation](https://docs.agentcontrol.dev/sdk/python-sdk) for complete reference.

## Supplying available tools to an LLM control

The `@control` decorator is a convenience path for function-based steps. An LLM
control can include static tool definitions, or a provider can build them from
the function arguments for each pre- and post-execution check:

```python
AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search internal documents",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]

@agent_control.control(step_type="llm", tools=AVAILABLE_TOOLS)
async def answer(message: str) -> str:
    ...
```

For per-call tools, pass a provider such as
`tools=lambda args, kwargs: tools_for(kwargs.get("model"))`. The provider may
return `None` when the step has no available tools.

For framework adapters and advanced callers, construct the shared `Step`
directly and send it through the SDK's `check_evaluation` helper. This keeps
framework-specific message and tool formats in the adapter, without requiring
the decorator or a framework dependency:

```python
step = agent_control.Step(
    type="llm",
    name="openai_agent",
    input=messages,
    output=response,
    tools=available_tools,
)

async with agent_control.AgentControlClient() as client:
    result = await agent_control.evaluation.check_evaluation(
        client,
        agent_name="my-agent",
        step=step,
        stage="post",
    )
```

The existing `evaluate_controls` helper remains available for callers that
prefer its field-based convenience arguments.

## Sharing an OpenTelemetry provider with Google ADK

When Google ADK and Agent Control should export through the same OpenTelemetry
pipeline, configure one SDK `TracerProvider` and pass it to both components:

```python
import agent_control
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.instrumentation.google_adk import GoogleADKInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

resource = Resource.create({"service.name": "my-google-adk-agent"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)

GoogleADKInstrumentor().instrument(tracer_provider=provider)
agent_control.init(
    agent_name="my-google-adk-agent",
    observability_enabled=True,
    observability_sink_name="otel",
    observability_sink_config={"enabled": True},
    otel_tracer_provider=provider,
)
```

Agent Control reuses this provider without adding an exporter or span processor.
It force-flushes the provider during shutdown but leaves provider shutdown to the
application. If no provider is passed, the OTEL sink first checks for a globally
registered SDK provider, then falls back to its existing Agent Control-owned OTLP
pipeline.
