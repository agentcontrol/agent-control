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
