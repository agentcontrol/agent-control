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
`tools=lambda args, kwargs: tools_for(kwargs.get("model"))`. The provider
receives the raw positional call arguments in `args` and keyword arguments in
`kwargs` for each pre- and post-execution check. The provider may return `None`
when the step has no available tools.

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


## Whole control-check elapsed time

`evaluate_controls()`, `check_evaluation_with_local()` and the server-only
`evaluation.check_evaluation()` return `EvaluationResult.control_check_elapsed_ms`
and a unique `control_check_id`. Each value measures **one pre or post check**
with a monotonic clock. It includes preparation inside the evaluation helper,
local controls, and the conditional server call (network/auth refresh/retry wait
included). It excludes `init()`, decorator payload preparation before the helper,
the protected tool/LLM function, and export of the whole-check event itself.
High-level `evaluate_controls()` step construction and client setup happen before
the timed helper and are excluded, as is parent trace-context resolution.
The decorator server-only fallback also measures its HTTP evaluation attempt;
its already-built payload and client initialization are outside that boundary.
If local evaluation fails and the decorator falls back, these are separate check
attempts with separate IDs rather than one fabricated combined elapsed value.
Existing per-control `execution_duration_ms` values are unchanged.

```python
# After agent_control.init(...) has configured the SDK session.
result = await agent_control.evaluate_controls(
    agent_name="my-agent", step_name="search", input={"query": "example"},
    stage="pre", step_type="tool"
)
print(result.control_check_id, result.control_check_elapsed_ms)
```

Local denial, a completed result containing evaluator errors, and a check with
no applicable controls still have measured elapsed time. The last case measures
the check's preparation, rather than assigning zero as a placeholder. A genuinely
measured zero is valid. Older/manually constructed results have `None` unless
actually measured by these helpers. An SDK check that raises or is cancelled
still propagates that outcome; it does not return a fabricated evaluation result.

With observability enabled and an `otel` sink selected, the same provider emits
one `agent_control.control_check` span as a child of the correlated step. Its
start is captured when the check begins and its end uses that start plus measured
monotonic elapsed nanoseconds; these are not reconstructed from control children.
Attributes include `agent_control.control_check_elapsed_ms`, the check ID,
`check_stage`, and `control_check_status` (`completed`, `error`, `cancelled`).
Safe IDs/stage/elapsed/status are also supplied in the JSON `metadata` attribute.
No input/output or exception text is recorded. Existing Orbit ingestion treats
this as a workflow span; it is **not** an individual shield/control span. Showing
these spans/metadata in a dedicated session summary requires UI/Orbit follow-up.

Existing HTTP control-event ingestion accepts only individual control events;
it does not receive whole-check events. Custom registered sinks may opt in by
implementing `agent_control_telemetry.ControlCheckEventSink` in addition to their
existing `write_events` method. Control-only sinks remain compatible. Sink
failures never replace a result, exception or cancellation.

An elapsed value is neither an average nor the maximum of child controls.
Several checks may overlap in a session, so summing their elapsed values does
not establish session wall time or a counterfactual "agent overhead".
