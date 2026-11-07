"""Opt-in OTLP tracing of evaluation requests and their parallel controls."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass

from agent_control_models.runtime_tracing import Attributes, configure_runtime_tracing
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestSpan:
    trace_id: str
    sampled: bool
    set_http_status: Callable[[int], None]


_request_span_factory: Callable[[Mapping[str, str]], AbstractContextManager[RequestSpan]] | None = (
    None
)
_shutdown: Callable[[], None] | None = None


def _sample_ratio() -> float:
    try:
        ratio = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "0.01"))
        if math.isfinite(ratio) and 0 <= ratio <= 1:
            return ratio
    except ValueError:
        pass
    logger.warning("Invalid OTEL_TRACES_SAMPLER_ARG; using 0.01")
    return 0.01


def initialize_runtime_tracing() -> None:
    """Enable tracing only with an explicit OTLP/HTTP trace endpoint and optional extra."""
    global _request_span_factory, _shutdown
    endpoint = (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    )
    if not endpoint or _request_span_factory is not None:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    except ImportError:
        logger.warning("Runtime tracing unavailable; install agent-control-server[otel]")
        return

    headers: dict[str, str] = {}
    for variable in ("OTEL_EXPORTER_OTLP_HEADERS", "GALILEO_OTEL_AUTH_HEADER"):
        for pair in os.environ.get(variable, "").split(","):
            key, separator, value = pair.partition("=")
            if separator and key.strip():
                headers[key.strip().lower()] = value.strip()
    resource = {
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "agent-control"),
        "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "galileo"),
    }
    for attribute, variable in (
        ("k8s.pod.name", "HOSTNAME"),
        ("k8s.namespace.name", "POD_NAMESPACE"),
    ):
        if resource_value := os.environ.get(variable):
            resource[attribute] = resource_value
    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider):
        provider = existing
    else:
        provider = TracerProvider(
            resource=Resource.create(resource),
            sampler=ParentBased(TraceIdRatioBased(_sample_ratio())),
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
        )
        trace.set_tracer_provider(provider)
        if trace.get_tracer_provider() is not provider:
            provider.shutdown()
            logger.warning("Runtime tracing requires the configured process tracer provider")
            return
        _shutdown = provider.shutdown
    tracer = trace.get_tracer("agent_control.runtime")
    propagator = TraceContextTextMapPropagator()

    @contextmanager
    def span_factory(name: str, attributes: Attributes) -> Iterator[None]:
        if not trace.get_current_span().is_recording():
            yield
            return
        kind = (
            trace.SpanKind.CLIENT
            if name == "agentcontrol.stage.luna_http"
            else trace.SpanKind.INTERNAL
        )
        with tracer.start_as_current_span(
            name,
            kind=kind,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield
            except BaseException as exc:
                span.set_attribute(
                    "galileo.outcome",
                    "cancelled" if isinstance(exc, asyncio.CancelledError) else "error",
                )
                span.set_status(trace.StatusCode.ERROR)
                raise

    def interval(name: str, started_ns: int, ended_ns: int) -> None:
        if trace.get_current_span().is_recording():
            span = tracer.start_span(name, start_time=started_ns, record_exception=False)
            span.end(end_time=max(started_ns, ended_ns))

    @contextmanager
    def request_span(carrier: Mapping[str, str]) -> Iterator[RequestSpan]:
        with tracer.start_as_current_span(
            "POST /api/v1/evaluation",
            context=propagator.extract(carrier),
            kind=trace.SpanKind.SERVER,
            attributes={"http.request.method": "POST", "http.route": "/api/v1/evaluation"},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:

            def set_http_status(status: int) -> None:
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(trace.StatusCode.ERROR)

            try:
                yield RequestSpan(
                    format(span.get_span_context().trace_id, "032x"),
                    span.is_recording(),
                    set_http_status,
                )
            except BaseException:
                span.set_status(trace.StatusCode.ERROR)
                raise

    configure_runtime_tracing(span_factory, propagator.inject, interval)
    _request_span_factory = request_span
    logger.info("Runtime OTLP tracing enabled (sample ratio=%s)", _sample_ratio())


def shutdown_runtime_tracing() -> None:
    global _request_span_factory, _shutdown
    configure_runtime_tracing(None)
    _request_span_factory = None
    if _shutdown is not None:
        _shutdown()
        _shutdown = None


class RuntimeTracingMiddleware:
    """Continue W3C context and expose the trace ID without reading request bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        factory = _request_span_factory
        if (
            factory is None
            or scope["type"] != "http"
            or scope.get("path") != "/api/v1/evaluation"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return
        carrier = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
            if key.lower() in (b"traceparent", b"tracestate")
        }
        with factory(carrier) as span:

            async def traced_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    span.set_http_status(message["status"])
                    message = dict(message)
                    message["headers"] = [
                        *message.get("headers", []),
                        (b"x-galileo-trace-id", span.trace_id.encode("ascii")),
                        (b"x-galileo-trace-sampled", b"1" if span.sampled else b"0"),
                    ]
                await send(message)

            await self.app(scope, receive, traced_send)
