"""Build public Galileo records from Agent Control evaluation inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from agent_control_models import Step
from pydantic import BaseModel
from splunk_ao import (  # type: ignore[import-untyped]
    LlmSpan,
    RetrieverSpan,
    Session,
    ToolSpan,
    Trace,
)

from .normalization import (
    documents,
    message_value,
    session_value,
    string_metadata,
    text_value,
    tool_value,
    trace_input_value,
    trace_output_value,
)

type GalileoRecord = LlmSpan | ToolSpan | RetrieverSpan | Trace | Session
type GalileoSpan = LlmSpan | ToolSpan | RetrieverSpan

_MISSING = object()
_SPAN_TYPES = {"llm", "tool", "retriever"}
_RECORD_TYPES = _SPAN_TYPES | {"trace", "session"}


class RecordFactoryError(ValueError):
    """Base error raised when an Agent Control step cannot become a record."""


class UnsupportedStepTypeError(RecordFactoryError):
    """Raised when a step type has no supported public Galileo record."""


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _selected_values(
    selected_data: Any,
    *,
    payload_field: str,
) -> tuple[Any, Any]:
    if isinstance(selected_data, Mapping) and (
        "input" in selected_data or "output" in selected_data
    ):
        return selected_data.get("input"), selected_data.get("output")
    if payload_field == "output":
        return None, selected_data
    return selected_data, None


def _child_payloads(context: Mapping[str, Any], *, key: str) -> list[Any]:
    value: Any = context.get(key)
    if value is None and key == "spans":
        value = context.get("children")
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise RecordFactoryError(f"Galileo {key} context must be a list.")
    return list(value)


def _span_payloads(raw: Mapping[str, Any], context: Mapping[str, Any]) -> list[Any]:
    """Read child spans from either a public model dump or step context."""
    if "spans" in raw:
        value = raw["spans"]
        if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
            raise RecordFactoryError("Galileo span context must include a 'spans' list.")
        return list(value)
    return _child_payloads(context, key="spans")


def _nested_record(value: Any) -> GalileoRecord:
    if isinstance(value, (LlmSpan, ToolSpan, RetrieverSpan, Trace, Session)):
        return value
    raw = _mapping(value)
    if raw is None:
        raise RecordFactoryError("Nested Galileo records must be objects with a supported type.")
    raw_type_value = raw.get("type")
    raw_type = (
        raw_type_value
        if isinstance(raw_type_value, str)
        else getattr(raw_type_value, "value", None)
    )
    if not isinstance(raw_type, str):
        raise RecordFactoryError("Nested Galileo records require a string 'type'.")
    if raw_type not in _RECORD_TYPES:
        raise UnsupportedStepTypeError(f"Unsupported Galileo nested step type: {raw_type!r}")
    return _record_from_mapping(raw, raw_type)


def _nested_span(value: Any) -> GalileoSpan:
    record = _nested_record(value)
    if not isinstance(record, (LlmSpan, ToolSpan, RetrieverSpan)):
        raise RecordFactoryError("Nested span context must contain a span record.")
    return record


def _record_from_mapping(raw: Mapping[str, Any], record_type: str) -> GalileoRecord:
    context = _mapping(raw.get("context")) or {}
    common = {
        "name": "" if raw.get("name") is None else str(raw["name"]),
        "user_metadata": string_metadata(raw.get("user_metadata", raw.get("metadata"))),
    }
    for field in (
        "tags",
        "status_code",
        "external_id",
        "step_number",
        "created_at",
        "metrics",
        "dataset_input",
        "dataset_output",
        "dataset_metadata",
    ):
        if raw.get(field) is not None:
            common[field] = (
                text_value(raw[field])
                if field in {"dataset_input", "dataset_output"}
                else string_metadata(raw[field])
                if field == "dataset_metadata"
                else raw[field]
            )

    input_value = raw.get("input")
    output_value = raw.get("output")
    if record_type == "llm":
        kwargs = {
            **common,
            "input": message_value(input_value),
            "output": message_value(output_value, output=True),
        }
        if raw.get("tools") is not None:
            kwargs["tools"] = raw["tools"]
        for field in ("events", "model", "temperature", "finish_reason"):
            if raw.get(field) is not None:
                kwargs[field] = raw[field]
        if raw.get("redacted_input") is not None:
            kwargs["redacted_input"] = message_value(raw["redacted_input"])
        if raw.get("redacted_output") is not None:
            kwargs["redacted_output"] = message_value(raw["redacted_output"], output=True)
        return LlmSpan(**kwargs)
    if record_type == "tool":
        kwargs = {
            **common,
            "input": tool_value(input_value) or "",
            "output": tool_value(output_value),
        }
        if raw.get("tool_call_id") is not None:
            kwargs["tool_call_id"] = str(raw["tool_call_id"])
        if raw.get("redacted_input") is not None:
            kwargs["redacted_input"] = tool_value(raw["redacted_input"])
        if raw.get("redacted_output") is not None:
            kwargs["redacted_output"] = tool_value(raw["redacted_output"])
        kwargs["spans"] = [_nested_span(item) for item in _span_payloads(raw, context)]
        return ToolSpan(**kwargs)
    if record_type == "retriever":
        kwargs = {**common, "input": text_value(input_value), "output": documents(output_value)}
        if raw.get("redacted_input") is not None:
            kwargs["redacted_input"] = text_value(raw["redacted_input"])
        if raw.get("redacted_output") is not None:
            kwargs["redacted_output"] = documents(raw["redacted_output"])
        kwargs["spans"] = [_nested_span(item) for item in _span_payloads(raw, context)]
        return RetrieverSpan(**kwargs)
    if record_type == "trace":
        spans = raw.get("spans", context.get("spans", context.get("children")))
        if not isinstance(spans, Sequence) or isinstance(spans, str | bytes | bytearray):
            raise RecordFactoryError("Galileo trace context must include a 'spans' list.")
        trace_kwargs: dict[str, Any] = {
            **common,
            "input": trace_input_value(input_value),
            "output": trace_output_value(output_value),
            "spans": [_nested_span(item) for item in spans],
        }
        if raw.get("redacted_input") is not None:
            trace_kwargs["redacted_input"] = trace_input_value(raw["redacted_input"])
        if raw.get("redacted_output") is not None:
            trace_kwargs["redacted_output"] = trace_output_value(raw["redacted_output"])
        return Trace(
            **trace_kwargs,
        )
    traces = raw.get("traces", context.get("traces"))
    if not isinstance(traces, Sequence) or isinstance(traces, str | bytes | bytearray):
        raise RecordFactoryError("Galileo session context must include a 'traces' list.")
    nested_records = [_nested_record(item) for item in traces]
    nested_traces = [item for item in nested_records if isinstance(item, Trace)]
    if len(nested_traces) != len(nested_records):
        raise RecordFactoryError("Galileo session 'traces' must contain trace records.")
    session_kwargs: dict[str, Any] = {
        **common,
        "input": session_value(input_value),
        "output": session_value(output_value),
        "traces": cast(list[Trace], nested_traces),
    }
    if raw.get("redacted_input") is not None:
        session_kwargs["redacted_input"] = session_value(raw["redacted_input"])
    if raw.get("redacted_output") is not None:
        session_kwargs["redacted_output"] = session_value(raw["redacted_output"])
    return Session(
        **session_kwargs,
    )


def record_from_step(
    step: Step,
    *,
    selected_input: Any = _MISSING,
    selected_output: Any = _MISSING,
    selected_data: Any = _MISSING,
    payload_field: str = "input",
) -> GalileoRecord:
    """Build a canonical Galileo record from a complete Agent Control step.

    The complete step determines the record discriminator. Selector-selected
    values override only the corresponding input/output fields, preserving the
    selected evaluator payload while the unselected side comes from ``step``.
    Trace and session records require structured child context; scalar selected
    values are never promoted into those record types.
    """
    if not isinstance(step, Step):
        raise RecordFactoryError("A complete Agent Control Step is required.")
    record_type = step.type.strip().lower()
    if record_type not in _RECORD_TYPES:
        raise UnsupportedStepTypeError(f"Unsupported Agent Control step type: {step.type!r}")

    if selected_data is not _MISSING:
        selected_input, selected_output = _selected_values(
            selected_data,
            payload_field=payload_field,
        )
    context = dict(_mapping(step.context) or {})
    step_envelope = _mapping(step.input)
    if record_type == "trace" and not context and step_envelope is not None:
        if "spans" in step_envelope or "children" in step_envelope:
            context = dict(step_envelope)
    if record_type == "session" and not context and step_envelope is not None:
        if "traces" in step_envelope:
            context = dict(step_envelope)
    input_value = (
        step.input if selected_input is _MISSING or selected_input is None else selected_input
    )
    output_value = (
        step.output if selected_output is _MISSING or selected_output is None else selected_output
    )
    if selected_input is _MISSING or selected_input is None:
        if step_envelope is not None and record_type in {"trace", "session"}:
            input_value = step_envelope.get("input", step.input)
    if selected_output is _MISSING or selected_output is None:
        if step_envelope is not None and record_type in {"trace", "session"}:
            output_value = step_envelope.get("output", step.output)

    if record_type in {"trace", "session"}:
        selected_value = selected_data
        if selected_data is _MISSING:
            selected_value = selected_input if selected_input is not _MISSING else _MISSING
        if selected_value is not _MISSING and selected_value is not None and not isinstance(
            selected_value, Mapping
        ):
            raise RecordFactoryError(
                f"Galileo {record_type} records require structured context; "
                "an untyped scalar selector value is not sufficient."
            )
    if record_type == "trace" and not (
        "spans" in context or "children" in context or isinstance(context.get("trace"), Mapping)
    ):
        raise RecordFactoryError("Galileo trace context is missing; provide a 'spans' list.")
    if record_type == "session" and not (
        "traces" in context or isinstance(context.get("session"), Mapping)
    ):
        raise RecordFactoryError("Galileo session context is missing; provide a 'traces' list.")

    source: dict[str, Any] = {
        "type": record_type,
        "name": step.name,
        "input": input_value,
        "output": output_value,
        "context": context,
        "tools": step.tools,
    }
    if record_type == "trace" and isinstance(context.get("trace"), Mapping):
        source.update(context["trace"])
    if record_type == "session" and isinstance(context.get("session"), Mapping):
        source.update(context["session"])
    if selected_input is not _MISSING and selected_input is not None:
        source["input"] = input_value
    if selected_output is not _MISSING and selected_output is not None:
        source["output"] = output_value
    if step.ground_truth is not None:
        source["dataset_output"] = step.ground_truth
    source["metadata"] = context.get("metadata")
    return _record_from_mapping(source, record_type)


def record_from_scorer_invoke_record(record: BaseModel) -> GalileoRecord:
    """Convert the legacy Pydantic Luna request record to a canonical record.

    The Luna wire contract intentionally remains owned by
    :class:`ScorerInvokeRecord`. This adapter accepts that existing request
    model at the boundary and uses the published SDK models internally.
    """
    raw = record.model_dump(mode="python", exclude_none=True)
    record_type = raw.get("type")
    if not isinstance(record_type, str) or record_type not in _RECORD_TYPES:
        raise UnsupportedStepTypeError(f"Unsupported Galileo record type: {record_type!r}")
    return _record_from_mapping(raw, record_type)


def build_record(selected_data: Any, step: Step, *, payload_field: str = "input") -> GalileoRecord:
    """Build a Galileo record using the evaluator's selected data."""
    return record_from_step(step, selected_data=selected_data, payload_field=payload_field)


def build_galileo_record(
    selected_data: Any,
    step: Step,
    *,
    payload_field: str = "input",
) -> GalileoRecord:
    """Alias for :func:`build_record` for explicit public use."""
    return build_record(selected_data, step, payload_field=payload_field)
