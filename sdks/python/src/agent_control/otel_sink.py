"""OpenTelemetry sink support for Agent Control control-execution events."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from agent_control_models import ControlExecutionEvent, JSONObject
from agent_control_telemetry.sinks import BaseControlEventSink, SinkResult

from .settings import get_settings
from .tracing import _generate_span_id, validate_span_id, validate_trace_id

logger = logging.getLogger(__name__)

OTEL_CONTROL_EVENT_SINK_NAME = "otel"
_OTEL_INSTRUMENTATION_SCOPE = "agent_control.observability"
_OTEL_NOOP_WARNING = (
    "OpenTelemetry sink selected but OpenTelemetry SDK/exporter dependencies are not available; "
    "control events will be accepted without being exported"
)
_OTEL_EXPORTER_MISSING_WARNING = (
    "OpenTelemetry sink selected but no OTLP exporter configuration was found; "
    "control events will not be exported"
)

AttributeValue = str | bool | int | float | list[str] | list[bool] | list[int] | list[float]


@dataclass(frozen=True)
class OTELControlEventSpan:
    """Normalized OTEL span payload derived from a control event."""

    name: str
    trace_id: str
    parent_span_id: str
    attributes: dict[str, AttributeValue]
    start_time_unix_nano: int
    end_time_unix_nano: int
    error_message: str | None = None


@dataclass(frozen=True)
class OTELSinkConfig:
    """Configuration for OTEL sink creation."""

    enabled: bool
    endpoint: str | None
    headers: dict[str, str]
    service_name: str


@dataclass(frozen=True)
class OTELSDKModules:
    """References to the OTEL SDK classes/functions used by the sink."""

    tracer_provider_cls: type[Any]
    resource_cls: type[Any]
    batch_span_processor_cls: type[Any]
    otlp_span_exporter_cls: type[Any]
    span_context_cls: type[Any]
    non_recording_span_cls: type[Any]
    trace_flags_cls: type[Any]
    trace_state_cls: type[Any]
    status_cls: type[Any]
    status_code_cls: type[Any]
    span_kind: Any
    set_span_in_context: Any


def _to_unix_nano(timestamp: datetime, /) -> int:
    return int(timestamp.astimezone(UTC).timestamp() * 1_000_000_000)


def _normalize_attribute_value(value: object) -> AttributeValue:
    """Coerce arbitrary metadata into a value OTEL span attributes accept."""
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        if all(isinstance(item, bool) for item in value):
            return [item for item in value]
        if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
            return [item for item in value]
        if all(isinstance(item, float) for item in value):
            return [item for item in value]
        if all(isinstance(item, str) for item in value):
            return [item for item in value]
    if isinstance(value, tuple):
        return _normalize_attribute_value(list(value))
    return json.dumps(value, default=str, sort_keys=True)


def control_event_to_otel_span(event: ControlExecutionEvent) -> OTELControlEventSpan:
    """Convert a control-execution event into OTEL span data."""
    end_time_unix_nano = _to_unix_nano(event.timestamp)
    if event.execution_duration_ms is not None:
        start_time_unix_nano = max(
            0,
            end_time_unix_nano - int(event.execution_duration_ms * 1_000_000),
        )
    else:
        start_time_unix_nano = end_time_unix_nano

    attributes: dict[str, AttributeValue] = {
        "agent_control.control_execution_id": event.control_execution_id,
        "agent_control.agent_name": event.agent_name,
        "agent_control.control_id": event.control_id,
        "agent_control.control_name": event.control_name,
        "agent_control.check_stage": event.check_stage,
        "agent_control.applies_to": event.applies_to,
        "agent_control.action": event.action,
        "agent_control.matched": event.matched,
        "agent_control.confidence": event.confidence,
        "agent_control.event_timestamp": event.timestamp.isoformat(),
    }

    if event.execution_duration_ms is not None:
        attributes["agent_control.execution_duration_ms"] = event.execution_duration_ms
    if event.evaluator_name is not None:
        attributes["agent_control.evaluator_name"] = event.evaluator_name
    if event.selector_path is not None:
        attributes["agent_control.selector_path"] = event.selector_path
    if event.error_message is not None:
        attributes["agent_control.error_message"] = event.error_message

    for key, value in sorted(event.metadata.items()):
        attributes[f"agent_control.metadata.{key}"] = _normalize_attribute_value(value)

    return OTELControlEventSpan(
        name="agent_control.control_execution",
        trace_id=event.trace_id,
        parent_span_id=event.span_id,
        attributes=attributes,
        start_time_unix_nano=start_time_unix_nano,
        end_time_unix_nano=end_time_unix_nano,
        error_message=event.error_message,
    )


class _NoOpControlEventSink(BaseControlEventSink):
    """Sink that accepts events but intentionally emits nothing."""

    def is_active(self) -> bool:
        return False

    def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        return SinkResult(accepted=len(events), dropped=0)


class OTELControlEventSink(BaseControlEventSink):
    """Emit control-execution events as OpenTelemetry spans."""

    def __init__(
        self,
        *,
        tracer_provider: Any,
        tracer: Any,
        sdk_modules: OTELSDKModules,
    ) -> None:
        self._tracer_provider: Any = tracer_provider
        self._tracer: Any = tracer
        self._sdk_modules = sdk_modules

    def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        accepted = 0
        dropped = 0

        for event in events:
            try:
                self._write_event(event)
                accepted += 1
            except Exception:
                logger.warning("Failed to emit control event to OTEL", exc_info=True)
                dropped += 1

        return SinkResult(accepted=accepted, dropped=dropped)

    def flush(self) -> None:
        force_flush = getattr(self._tracer_provider, "force_flush", None)
        if callable(force_flush):
            force_flush()

    def close(self) -> None:
        shutdown = getattr(self._tracer_provider, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def _write_event(self, event: ControlExecutionEvent) -> None:
        span_data = control_event_to_otel_span(event)
        parent_context = self._build_parent_context(span_data)
        span = self._tracer.start_span(
            span_data.name,
            context=parent_context,
            kind=self._sdk_modules.span_kind.INTERNAL,
            start_time=span_data.start_time_unix_nano,
        )
        span.set_attributes(span_data.attributes)
        if span_data.error_message:
            record_exception = getattr(span, "record_exception", None)
            if callable(record_exception):
                record_exception(RuntimeError(span_data.error_message))
            set_status = getattr(span, "set_status", None)
            if callable(set_status):
                set_status(
                    self._sdk_modules.status_cls(
                        self._sdk_modules.status_code_cls.ERROR,
                        span_data.error_message,
                    )
                )
        span.end(end_time=span_data.end_time_unix_nano)

    def _build_parent_context(self, span_data: OTELControlEventSpan) -> object | None:
        trace_id = span_data.trace_id
        parent_span_id = span_data.parent_span_id

        if not validate_trace_id(trace_id) or trace_id == "0" * 32:
            return None
        if not validate_span_id(parent_span_id) or parent_span_id == "0" * 16:
            parent_span_id = _generate_span_id()

        parent_span_context = self._sdk_modules.span_context_cls(
            trace_id=int(trace_id, 16),
            span_id=int(parent_span_id, 16),
            is_remote=True,
            trace_flags=self._sdk_modules.trace_flags_cls(
                self._sdk_modules.trace_flags_cls.SAMPLED
            ),
            trace_state=self._sdk_modules.trace_state_cls(),
        )
        return cast(
            object,
            self._sdk_modules.set_span_in_context(
                self._sdk_modules.non_recording_span_cls(parent_span_context)
            ),
        )


def _resolve_otel_sink_config(config: JSONObject) -> OTELSinkConfig:
    """Resolve OTEL sink config from settings with per-sink overrides."""
    settings = get_settings()

    enabled = bool(config.get("enabled", settings.otel_enabled))

    endpoint_value = config.get("endpoint", settings.otel_endpoint)
    endpoint = str(endpoint_value) if endpoint_value else None

    headers_value = config.get("headers", settings.otel_headers)
    headers: dict[str, str] = {}
    if isinstance(headers_value, dict):
        headers = {str(key): str(value) for key, value in headers_value.items()}

    service_name_value = config.get("service_name", settings.otel_service_name)
    service_name = str(service_name_value) if service_name_value else "agent-control-sdk"

    return OTELSinkConfig(
        enabled=enabled,
        endpoint=endpoint,
        headers=headers,
        service_name=service_name,
    )


def _has_explicit_otel_exporter_configuration(config: OTELSinkConfig) -> bool:
    """Return whether an OTLP exporter should be configured for the sink."""
    if config.endpoint:
        return True
    return bool(
        os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def _load_otel_sdk_modules() -> OTELSDKModules:
    """Import OTEL SDK modules on demand so the sink remains optional."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-not-found]
    from opentelemetry.trace import (  # type: ignore[import-not-found]
        NonRecordingSpan,
        SpanContext,
        SpanKind,
        Status,
        StatusCode,
        TraceFlags,
        TraceState,
        set_span_in_context,
    )

    return OTELSDKModules(
        tracer_provider_cls=TracerProvider,
        resource_cls=Resource,
        batch_span_processor_cls=BatchSpanProcessor,
        otlp_span_exporter_cls=OTLPSpanExporter,
        span_context_cls=SpanContext,
        non_recording_span_cls=NonRecordingSpan,
        trace_flags_cls=TraceFlags,
        trace_state_cls=TraceState,
        status_cls=Status,
        status_code_cls=StatusCode,
        span_kind=SpanKind,
        set_span_in_context=set_span_in_context,
    )


def create_otel_control_event_sink(config: JSONObject) -> BaseControlEventSink:
    """Create the built-in OTEL control-event sink."""
    resolved_config = _resolve_otel_sink_config(config)
    if not resolved_config.enabled:
        return _NoOpControlEventSink()

    try:
        sdk_modules = _load_otel_sdk_modules()
    except ImportError:
        logger.warning(_OTEL_NOOP_WARNING)
        return _NoOpControlEventSink()

    resource = sdk_modules.resource_cls.create({"service.name": resolved_config.service_name})
    tracer_provider = sdk_modules.tracer_provider_cls(resource=resource)

    if not _has_explicit_otel_exporter_configuration(resolved_config):
        logger.warning(_OTEL_EXPORTER_MISSING_WARNING)
        shutdown = getattr(tracer_provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
        return _NoOpControlEventSink()

    exporter_kwargs: dict[str, object] = {}
    if resolved_config.endpoint:
        exporter_kwargs["endpoint"] = resolved_config.endpoint
    if resolved_config.headers:
        exporter_kwargs["headers"] = resolved_config.headers
    exporter = sdk_modules.otlp_span_exporter_cls(**exporter_kwargs)
    tracer_provider.add_span_processor(sdk_modules.batch_span_processor_cls(exporter))

    tracer = tracer_provider.get_tracer(_OTEL_INSTRUMENTATION_SCOPE)
    return OTELControlEventSink(
        tracer_provider=tracer_provider,
        tracer=tracer,
        sdk_modules=sdk_modules,
    )
