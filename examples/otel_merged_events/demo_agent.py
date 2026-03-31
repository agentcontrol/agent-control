#!/usr/bin/env python3
"""Inspect merged control events and the OTEL spans emitted from them."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

os.environ.setdefault("AGENT_CONTROL_OTEL_ENABLED", "true")
os.environ.setdefault("AGENT_CONTROL_OTEL_SERVICE_NAME", "agent-control-otel-demo")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import agent_control
from agent_control import AgentControlClient, emit_control_events, get_server_controls
from agent_control.evaluation import (
    _ControlAdapter,
    _build_server_control_lookup,
    _get_applicable_controls,
    _has_applicable_prefiltered_server_controls,
    _merge_results,
)
from agent_control.evaluation_events import build_control_execution_events
from agent_control.telemetry import has_control_event_sink
from agent_control.tracing import with_trace
from agent_control_engine.core import ControlEngine
from agent_control_models import ControlDefinition, EvaluationRequest, EvaluationResponse


AGENT_NAME = "otel-merged-events-demo-agent"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
MESSAGE = "local-trigger priority server-trigger elevated in one request"


def configure_in_memory_exporter() -> InMemorySpanExporter:
    """Configure a tracer provider that stores exported spans in memory.

    Args:
        None.

    Returns:
        The configured in-memory OTEL exporter.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "agent-control-otel-demo"})
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def print_json_block(title: str, payload: dict[str, Any]) -> None:
    """Print a titled JSON block.

    Args:
        title: Section title to print.
        payload: JSON-serializable payload.

    Returns:
        None.
    """
    print(f"\n{title}")
    print("-" * len(title))
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def print_event_summary(label: str, events: list[Any]) -> None:
    """Print a concise summary of reconstructed events.

    Args:
        label: Section label to print.
        events: Reconstructed control execution events.

    Returns:
        None.
    """
    print(f"\n{label}")
    print("-" * len(label))
    if not events:
        print("No events reconstructed.")
        return

    for event in events:
        print(
            f"- control={event.control_name} stage={event.check_stage} "
            f"matched={event.matched} action={event.action} "
            f"trace_id={event.trace_id} parent_span_id={event.span_id}"
        )


def print_event_details(label: str, events: list[Any]) -> None:
    """Print the full reconstructed control-event payloads.

    Args:
        label: Section label to print.
        events: Reconstructed control execution events.

    Returns:
        None.
    """
    print(f"\n{label}")
    print("-" * len(label))
    if not events:
        print("No events reconstructed.")
        return

    for index, event in enumerate(events, start=1):
        print_json_block(
            f"Event {index}",
            event.model_dump(mode="json"),
        )


def span_to_collector_payload(span: Any) -> dict[str, Any]:
    """Render a finished OTEL span as a collector-facing payload sample.

    Args:
        span: Finished span captured by the in-memory exporter.

    Returns:
        A simplified payload showing the fields an OTEL collector/backend
        typically receives and indexes.
    """
    resource = {}
    if getattr(span, "resource", None) is not None:
        resource = dict(sorted(dict(span.resource.attributes).items()))

    return {
        "resource": resource,
        "scope": {
            "name": getattr(getattr(span, "instrumentation_scope", None), "name", None),
            "version": getattr(
                getattr(span, "instrumentation_scope", None), "version", None
            ),
        },
        "span": {
            "name": span.name,
            "trace_id": f"{span.context.trace_id:032x}",
            "span_id": f"{span.context.span_id:016x}",
            "parent_span_id": (
                f"{span.parent.span_id:016x}" if span.parent is not None else None
            ),
            "start_time_unix_nano": span.start_time,
            "end_time_unix_nano": span.end_time,
            "attributes": dict(sorted(dict(span.attributes).items())),
        },
    }


def empty_response() -> EvaluationResponse:
    """Return an empty evaluation response for merge convenience.

    Args:
        None.

    Returns:
        An empty successful evaluation response.
    """
    return EvaluationResponse(
        is_safe=True,
        confidence=1.0,
        reason=None,
        matches=None,
        errors=None,
        non_matches=None,
    )


def partition_controls(
    controls: list[dict[str, Any]],
) -> tuple[list[_ControlAdapter], list[dict[str, Any]]]:
    """Split cached controls into SDK-local and server-side groups.

    Args:
        controls: Raw control payloads cached in the SDK.

    Returns:
        A tuple of parsed SDK-local controls and raw server control payloads.
    """
    local_controls: list[_ControlAdapter] = []
    server_control_payloads: list[dict[str, Any]] = []

    for control in controls:
        control_data = control.get("control", {})
        if control_data.get("execution", "server") == "sdk":
            local_controls.append(
                _ControlAdapter(
                    id=control["id"],
                    name=control["name"],
                    control=ControlDefinition.model_validate(control_data),
                )
            )
        else:
            server_control_payloads.append(control)

    return local_controls, server_control_payloads


async def run_walkthrough(exporter: InMemorySpanExporter) -> None:
    """Run the merged-event walkthrough and print each intermediate artifact.

    Args:
        exporter: In-memory OTEL exporter that records finished spans.

    Returns:
        None.
    """
    controls = get_server_controls() or []
    local_controls, server_control_payloads = partition_controls(controls)
    request = EvaluationRequest(
        agent_name=AGENT_NAME,
        step={"type": "llm", "name": "draft_answer", "input": MESSAGE},
        stage="pre",
    )

    print("=" * 80)
    print("Merged Control Events OTEL Demo")
    print("=" * 80)
    print(f"Input message: {MESSAGE}")
    print(f"Loaded controls: {len(controls)}")
    print(
        f"SDK-local controls: {[control.name for control in local_controls]} | "
        f"Server-side controls: {[control['name'] for control in server_control_payloads]}"
    )
    print(f"Merged-event sink registered: {has_control_event_sink()}")
    print(
        "Composite controls are ordered intentionally so the collector output shows "
        "different primary evaluator metadata for the local and server spans."
    )

    with with_trace() as (trace_id, span_id):
        print(f"Trace context: trace_id={trace_id} span_id={span_id}")

        applicable_local_controls = _get_applicable_controls(
            local_controls,
            request,
            context="sdk",
        )
        print(
            f"Applicable SDK-local controls on this input: "
            f"{[control.name for control in applicable_local_controls]}"
        )

        local_result = empty_response()
        local_events: list[Any] = []
        if applicable_local_controls:
            local_engine = ControlEngine(applicable_local_controls, context="sdk")
            local_result = await local_engine.process(request)
            local_lookup = {
                control.id: control.control for control in applicable_local_controls
            }
            local_events = build_control_execution_events(
                local_result,
                request,
                local_lookup,
                trace_id,
                span_id,
                AGENT_NAME,
            )

        print_json_block("Local evaluation response", local_result.model_dump(mode="json"))
        print_event_summary("Reconstructed local events", local_events)
        print_event_details("Local event details", local_events)

        server_result = empty_response()
        server_events: list[Any] = []
        if _has_applicable_prefiltered_server_controls(server_control_payloads, request):
            print(
                f"Applicable server-side controls on this input: "
                f"{[control['name'] for control in server_control_payloads]}"
            )
            async with AgentControlClient(base_url=SERVER_URL) as client:
                response = await client.http_client.post(
                    "/api/v1/evaluation",
                    json=request.model_dump(mode="json", exclude_none=True),
                    headers={
                        "X-Trace-Id": trace_id,
                        "X-Span-Id": span_id,
                        "X-Agent-Control-Merge-Events": "true",
                    },
                )
                response.raise_for_status()
                server_result = EvaluationResponse.model_validate(response.json())

            server_lookup = _build_server_control_lookup(server_control_payloads)
            server_events = build_control_execution_events(
                server_result,
                request,
                server_lookup,
                trace_id,
                span_id,
                AGENT_NAME,
            )

        print_json_block("Server evaluation response", server_result.model_dump(mode="json"))
        print_event_summary("Reconstructed server events", server_events)
        print_event_details("Server event details", server_events)

        merged_result = _merge_results(local_result, server_result)
        merged_events = local_events + server_events

        print_json_block("Merged evaluation result", merged_result.model_dump(mode="json"))
        print_event_summary("Final merged event batch", merged_events)
        print_event_details("Merged event details", merged_events)

        emit_control_events(merged_events)
        spans = exporter.get_finished_spans()

        print("\nCollector output")
        print("----------------")
        print(f"Collected OTEL spans: {len(spans)}")
        for index, span in enumerate(spans, start=1):
            print_json_block(
                f"Collector payload for span {index}",
                span_to_collector_payload(span),
            )


async def main() -> None:
    """Initialize the demo agent and run the OTEL walkthrough.

    Args:
        None.

    Returns:
        None.
    """
    exporter = configure_in_memory_exporter()

    agent_control.init(
        agent_name=AGENT_NAME,
        agent_description="Demo agent for OTEL merged-event emission",
        server_url=SERVER_URL,
    )

    await run_walkthrough(exporter)


if __name__ == "__main__":
    asyncio.run(main())
