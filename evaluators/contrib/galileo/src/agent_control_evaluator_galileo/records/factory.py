"""Build public Galileo records from Agent Control evaluation inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_control_models import Step
from galileo_core.schemas.logging.session import Session
from galileo_core.schemas.logging.span import (
    AgentSpan,
    ControlSpan,
    LlmSpan,
    RetrieverSpan,
    ToolSpan,
    WorkflowSpan,
)
from galileo_core.schemas.logging.trace import Trace

from .normalization import GalileoRecordNormalizer

type GalileoRecord = LlmSpan | ToolSpan | RetrieverSpan | Trace | Session
type GalileoSpan = LlmSpan | ToolSpan | RetrieverSpan
type GalileoCoreSpan = AgentSpan | WorkflowSpan | LlmSpan | RetrieverSpan | ToolSpan | ControlSpan
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


def _span_children(children: list[GalileoRecord], *, parent_type: str) -> list[GalileoCoreSpan]:
    spans: list[GalileoCoreSpan] = []
    for child in children:
        if not isinstance(child, (LlmSpan, ToolSpan, RetrieverSpan)):
            raise RecordFactoryError(f"Galileo {parent_type} children must be span steps.")
        spans.append(child)
    return spans


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
    Trace and session records require child steps; scalar selected
    values are never promoted into those record types. The result is a concrete
    Galileo Core step model (a ``BaseStep`` subclass) that can be JSON-serialized
    and revalidated using that subtype's schema. The factory doesn't assign
    execution IDs or storage ownership fields.
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
    hierarchy_fields = {"children", "spans", "traces"}.intersection(context)
    if hierarchy_fields:
        fields = ", ".join(sorted(hierarchy_fields))
        raise RecordFactoryError(
            f"Step.context cannot define Galileo hierarchy fields ({fields}); "
            "use Step.children instead."
        )
    children = step.children or []
    allowed_child_types = {
        "trace": _SPAN_TYPES,
        "session": {"trace"},
        "tool": _SPAN_TYPES,
        "retriever": _SPAN_TYPES,
        "llm": set(),
    }[record_type]
    child_records: list[GalileoRecord] = []
    for child in children:
        if not isinstance(child, Step):
            raise RecordFactoryError("Step.children must contain Agent Control Step objects.")
        child_type = child.type.strip().lower()
        if child_type not in allowed_child_types:
            raise RecordFactoryError(
                f"Galileo {record_type} step cannot contain {child_type!r} child steps."
            )
        child_records.append(record_from_step(child))
    input_value = (
        step.input if selected_input is _MISSING or selected_input is None else selected_input
    )
    output_value = (
        step.output if selected_output is _MISSING or selected_output is None else selected_output
    )
    if record_type in {"trace", "session"}:
        selected_value = selected_data
        if selected_data is _MISSING:
            selected_value = selected_input if selected_input is not _MISSING else _MISSING
        if selected_value is not _MISSING and selected_value is not None and not isinstance(
            selected_value, Mapping
        ):
            raise RecordFactoryError(
                f"Galileo {record_type} records require structured selector values; "
                "an untyped scalar selector value is not sufficient."
            )
    common: dict[str, Any] = {
        "name": step.name,
        "user_metadata": GalileoRecordNormalizer.metadata(context.get("metadata")),
    }
    if step.ground_truth is not None:
        common["dataset_output"] = GalileoRecordNormalizer.json_text(step.ground_truth)
    if record_type == "llm":
        kwargs = {
            **common,
            "input": GalileoRecordNormalizer.llm_input(input_value),
            "output": GalileoRecordNormalizer.llm_output(output_value),
        }
        if step.tools is not None:
            kwargs["tools"] = GalileoRecordNormalizer.llm_tools(step.tools)
        return LlmSpan(**kwargs)
    if record_type == "tool":
        return ToolSpan(
            **common,
            input=GalileoRecordNormalizer.tool_input(input_value),
            output=GalileoRecordNormalizer.tool_output(output_value),
            spans=_span_children(child_records, parent_type=record_type),
        )
    if record_type == "retriever":
        return RetrieverSpan(
            **common,
            input=GalileoRecordNormalizer.retriever_input(input_value),
            output=GalileoRecordNormalizer.retriever_output(output_value),
            spans=_span_children(child_records, parent_type=record_type),
        )
    if record_type == "trace":
        return Trace(
            **common,
            input=GalileoRecordNormalizer.trace_input(input_value),
            output=GalileoRecordNormalizer.trace_output(output_value),
            spans=_span_children(child_records, parent_type=record_type),
        )
    traces = [child for child in child_records if isinstance(child, Trace)]
    if len(traces) != len(child_records):
        raise RecordFactoryError("Galileo session children must be trace steps.")
    return Session(
        **common,
        input=GalileoRecordNormalizer.session_input(input_value),
        output=GalileoRecordNormalizer.session_output(output_value),
        traces=traces,
    )


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
