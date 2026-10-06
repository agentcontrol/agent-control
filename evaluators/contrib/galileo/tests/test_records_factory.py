"""Tests for the shared Agent Control to Galileo record factory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

import pytest
from agent_control_evaluator_galileo.records import (
    GalileoRecordNormalizer,
    RecordFactoryError,
    UnsupportedStepTypeError,
    build_galileo_record,
    build_record,
    record_from_step,
)
from agent_control_models import Step
from galileo_core.schemas.logging.llm import Message
from galileo_core.schemas.logging.session import Session
from galileo_core.schemas.logging.span import LlmSpan, RetrieverSpan, ToolSpan
from galileo_core.schemas.logging.step import BaseStep
from galileo_core.schemas.logging.trace import Trace
from galileo_core.schemas.shared.content_parts import FileContentPart, TextContentPart
from galileo_core.schemas.shared.document import Document
from galileo_core.schemas.shared.records import BaseRecord, RecordTypeAdapter
from pydantic import BaseModel, Field


def test_required_galileo_core_public_exports_are_importable() -> None:
    assert all((LlmSpan, ToolSpan, RetrieverSpan, Trace, Session, Document, Message))


def test_factory_records_are_serializable_concrete_base_steps() -> None:
    # Given: one record of each type accepted by the Galileo factory
    records = [
        record_from_step(Step(type="llm", name="answer", input="question", output="answer")),
        record_from_step(Step(type="tool", name="search", input={"query": "q"}, output="result")),
        record_from_step(
            Step(type="retriever", name="retrieve", input="question", output=["document"])
        ),
        record_from_step(
            Step(
                type="trace",
                name="request",
                input="question",
                output="answer",
                children=[Step(type="llm", name="answer", input="question")],
            )
        ),
        record_from_step(
            Step(
                type="session",
                name="conversation",
                input="question",
                children=[
                    Step(
                        type="trace",
                        name="request",
                        input="question",
                        children=[Step(type="llm", name="answer", input="question")],
                    )
                ],
            )
        ),
    ]

    # When: each concrete Galileo step is serialized and parsed back through its own schema
    rebuilt = [
        type(record).model_validate(record.model_dump(mode="json", exclude_none=True))
        for record in records
    ]

    # Then: every concrete class remains a BaseStep and keeps its discriminator and children
    assert all(isinstance(record, BaseStep) for record in records)
    assert all(isinstance(record, BaseStep) for record in rebuilt)
    assert [record.type.value for record in rebuilt] == [
        "llm",
        "tool",
        "retriever",
        "trace",
        "session",
    ]
    assert isinstance(rebuilt[3], Trace)
    assert isinstance(rebuilt[4], Session)
    assert isinstance(rebuilt[3].spans[0], LlmSpan)
    assert isinstance(rebuilt[4].traces[0].spans[0], LlmSpan)


def test_factory_steps_convert_to_core_records_after_execution_ids_are_added() -> None:
    # Given: each root subtype emitted by the factory, plus caller-supplied IDs
    steps = [
        record_from_step(Step(type="llm", name="answer", input="question", output="answer")),
        record_from_step(Step(type="tool", name="search", input={"query": "q"}, output="result")),
        record_from_step(
            Step(type="retriever", name="retrieve", input="question", output=["document"])
        ),
        record_from_step(
            Step(type="trace", name="request", input="question", children=[])
        ),
        record_from_step(
            Step(type="session", name="conversation", input="question", children=[])
        ),
    ]
    project_id = uuid4()
    run_id = uuid4()
    session_id = uuid4()
    trace_id = uuid4()
    rebuilt_records: list[BaseRecord] = []

    # When: add execution IDs and relationships, then apply Galileo Core's record discriminator
    for step in steps:
        step_id = uuid4()
        values = step.model_dump(
            mode="python",
            exclude={
                "id",
                "project_id",
                "run_id",
                "session_id",
                "trace_id",
                "parent_id",
                "spans",
                "traces",
            },
        )
        values.update(id=step_id, project_id=project_id, run_id=run_id, type=step.type)
        if isinstance(step, Session):
            values["session_id"] = step_id
        elif isinstance(step, Trace):
            values.update(session_id=session_id, trace_id=step_id)
        else:
            values.update(session_id=session_id, trace_id=trace_id, parent_id=trace_id)
        rebuilt_records.append(RecordTypeAdapter.validate_python(values))

    # Then: the concrete step payloads satisfy Galileo Core's stored-record schemas
    assert all(isinstance(record, BaseRecord) for record in rebuilt_records)
    assert [record.type.value for record in rebuilt_records] == [
        "llm",
        "tool",
        "retriever",
        "trace",
        "session",
    ]


def test_llm_messages_use_public_canonical_validation() -> None:
    record = record_from_step(
        Step(
            type="llm",
            name="answer",
            input=[{"role": "user", "content": "question"}],
            output={"role": "assistant", "content": "answer"},
            ground_truth={"expected": "answer"},
        )
    )

    assert isinstance(record, LlmSpan)
    assert record.input[0].role.value == "user"
    assert record.output.role.value == "assistant"
    assert record.dataset_output == json.dumps({"expected": "answer"})


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("answer", "answer"),
        ({"role": "assistant", "content": "answer"}, "answer"),
    ],
)
def test_llm_scalar_and_dictionary_outputs_match_sdk(
    output: object,
    expected: str,
) -> None:
    record = record_from_step(Step(type="llm", name="answer", input="question", output=output))

    assert isinstance(record, LlmSpan)
    assert record.output.content == expected


@pytest.mark.parametrize(
    "output",
    [
        [{"role": "assistant", "content": "first"}],
        [
            {"role": "assistant", "content": "first"},
            {"role": "assistant", "content": "second"},
        ],
    ],
)
def test_llm_sequence_outputs_are_one_json_string_without_dropping_values(
    output: list[dict[str, str]],
) -> None:
    record = record_from_step(Step(type="llm", name="answer", input="question", output=output))

    assert isinstance(record, LlmSpan)
    assert record.output.role.value == "assistant"
    assert json.loads(record.output.content) == output


def test_llm_tuple_output_uses_the_same_sdk_serializer() -> None:
    output = ({"role": "assistant", "content": "first"}, {"role": "assistant", "content": "second"})

    record = record_from_step(Step(type="llm", name="answer", input="question", output=output))

    assert isinstance(record, LlmSpan)
    assert record.output.content == json.dumps(list(output))
    assert json.loads(record.output.content) == list(output)


def test_selected_mapping_and_output_payload_are_preserved() -> None:
    step = Step(type="llm", name="answer", input="base input", output="base output")

    selected_record = build_record(
        {"input": "selected input", "output": "selected output"}, step
    )
    output_record = build_record("selected output", step, payload_field="output")

    assert isinstance(selected_record, LlmSpan)
    assert isinstance(output_record, LlmSpan)
    assert selected_record.input[0].content == "selected input"
    assert selected_record.output.content == "selected output"
    assert output_record.output.content == "selected output"


def test_tool_values_are_json_strings_and_missing_output_stays_missing() -> None:
    record = record_from_step(
        Step(type="tool", name="search", input={"query": "q"}, output={"hits": [1, 2]})
    )
    missing_output = record_from_step(Step(type="tool", name="search", input={"query": "q"}))

    assert isinstance(record, ToolSpan)
    assert json.loads(record.input) == {"query": "q"}
    assert json.loads(record.output or "") == {"hits": [1, 2]}
    assert missing_output.output is None

    expected = ToolSpan(
        name="search",
        input=json.dumps({"query": "q"}),
        output=json.dumps({"hits": [1, 2]}),
    )
    assert type(record) is type(expected)
    assert record.input == expected.input
    assert record.output == expected.output


@pytest.mark.parametrize(
    "output",
    [None, "text", {"content": "document"}, {"invalid": True}, 42, ["one", "two"]],
)
def test_retriever_matches_sdk_document_coercion(output: object) -> None:
    record = record_from_step(
        Step(type="retriever", name="retrieve", input="question", output=output)
    )
    assert isinstance(record, RetrieverSpan)
    if output is None or isinstance(output, int):
        assert [document.content for document in record.output] == [""]
    elif isinstance(output, str):
        assert [document.content for document in record.output] == [output]
    elif isinstance(output, dict) and "content" in output:
        assert [document.content for document in record.output] == [output["content"]]
    elif output == ["one", "two"]:
        assert [document.content for document in record.output] == output
    else:
        assert record.output[0].content == json.dumps(output)


def test_retriever_rejects_mixed_lists_like_the_sdk_helper() -> None:
    output = ["one", {"content": "two"}]

    with pytest.raises(ValueError, match="Invalid document output"):
        record_from_step(Step(type="retriever", name="retrieve", input="question", output=output))


def test_retriever_results_become_documents_with_scalar_metadata_only() -> None:
    record = record_from_step(
        Step(
            type="retriever",
            name="retrieve",
            input="question",
            output=[
                {
                    "content": "context",
                    "metadata": {"score": 0.9, "source": "kb", "nested": {"bad": True}},
                }
            ],
        )
    )

    assert isinstance(record, RetrieverSpan)
    assert record.output[0].content == "context"
    assert record.output[0].metadata == {"score": 0.9, "source": "kb"}


def test_retriever_accepts_the_public_galileo_core_document_model() -> None:
    document = Document(content="context", metadata={"source": "kb"})
    record = RetrieverSpan.model_validate(
        {"name": "retrieve", "input": "question", "output": [document]}
    )

    assert isinstance(record, RetrieverSpan)
    assert record.output[0].content == "context"
    assert record.output[0].metadata == {"source": "kb"}


def test_public_document_metadata_variants_are_supported() -> None:
    document_without_metadata = Document(content="plain")
    document_with_model_metadata = Document.model_validate(
        {"content": "model metadata", "metadata": {"source": "kb"}}
    )

    record = RetrieverSpan.model_validate(
        {
            "input": "question",
            "output": [document_without_metadata, document_with_model_metadata],
        }
    )

    assert isinstance(record, RetrieverSpan)
    assert [document.model_dump() for document in record.output] == [
        {"content": "plain", "metadata": {}},
        {"content": "model metadata", "metadata": {"source": "kb"}},
    ]


def test_nested_trace_and_session_records_are_preserved() -> None:
    trace = record_from_step(
        Step(
            type="trace",
            name="request",
            input="question",
            children=[
                Step(
                    type="tool",
                    name="search",
                    input={"q": "x"},
                    children=[Step(type="tool", name="nested", input={"q": "y"})],
                ),
                Step(type="retriever", name="retrieve", input="x", output=[]),
            ],
        )
    )
    session = record_from_step(
        Step(
            type="session",
            name="conversation",
            input="question",
            children=[Step(type="trace", name="request", input="question", children=[
                Step(type="tool", name="search", input={"q": "x"}, children=[
                    Step(type="tool", name="nested", input={"q": "y"})
                ]),
                Step(type="retriever", name="retrieve", input="x", output=[]),
            ])],
        )
    )

    assert isinstance(trace, Trace)
    assert [type(span) for span in trace.spans] == [ToolSpan, RetrieverSpan]
    assert trace.spans[0].spans[0].name == "nested"
    assert isinstance(session, Session)
    assert len(session.traces) == 1
    assert session.traces[0].spans[0].name == "search"


def test_public_model_dump_preserves_canonical_fields() -> None:
    created_at = datetime(2024, 1, 1, tzinfo=UTC)
    llm_source = LlmSpan(
        input=[{"role": "user", "content": "question"}],
        output="answer",
        redacted_input=[{"role": "user", "content": "redacted question"}],
        redacted_output={"role": "assistant", "content": "redacted answer"},
        created_at=created_at,
        metrics={"duration_ns": 3},
        events=[{"type": "reasoning"}],
        model="model",
        temperature=0.2,
        finish_reason="stop",
    )
    tool_source = ToolSpan(
        input="input",
        output="output",
        redacted_input="redacted input",
        redacted_output="redacted output",
        created_at=created_at,
        metrics={"duration_ns": 4},
        tool_call_id="call-1",
    )
    retriever_source = RetrieverSpan(
        input="query",
        output=[{"content": "document"}],
        redacted_input="redacted query",
        redacted_output=[{"content": "redacted document"}],
        created_at=created_at,
        metrics={"duration_ns": 5},
    )
    trace_source = Trace(
        input="input",
        output="output",
        redacted_input="redacted input",
        redacted_output="redacted output",
        created_at=created_at,
        metrics={"duration_ns": 6},
        spans=[],
    )
    session_source = Session(
        input=[{"role": "user", "content": "input"}],
        output=[{"content": "output"}],
        redacted_input=[{"role": "user", "content": "redacted input"}],
        redacted_output=[{"content": "redacted output"}],
        created_at=created_at,
        metrics={"duration_ns": 7},
        traces=[],
    )

    rebuilt_llm = LlmSpan.model_validate(llm_source.model_dump(mode="json", exclude_none=True))
    rebuilt_tool = ToolSpan.model_validate(tool_source.model_dump(mode="json", exclude_none=True))
    rebuilt_retriever = RetrieverSpan.model_validate(
        retriever_source.model_dump(mode="json", exclude_none=True)
    )
    rebuilt_trace = Trace.model_validate(trace_source.model_dump(mode="json", exclude_none=True))
    rebuilt_session = Session.model_validate(
        session_source.model_dump(mode="json", exclude_none=True)
    )

    assert isinstance(rebuilt_llm, LlmSpan)
    assert rebuilt_llm.redacted_input[0].content == "redacted question"
    assert rebuilt_llm.redacted_output.content == "redacted answer"
    assert rebuilt_llm.created_at == created_at
    assert rebuilt_llm.metrics.duration_ns == 3
    assert rebuilt_llm.events == llm_source.events
    assert rebuilt_llm.model == "model"
    assert rebuilt_llm.temperature == 0.2
    assert rebuilt_llm.finish_reason == "stop"
    assert isinstance(rebuilt_tool, ToolSpan)
    assert rebuilt_tool.redacted_input == "redacted input"
    assert rebuilt_tool.redacted_output == "redacted output"
    assert rebuilt_tool.metrics.duration_ns == 4
    assert rebuilt_tool.tool_call_id == "call-1"
    assert isinstance(rebuilt_retriever, RetrieverSpan)
    assert rebuilt_retriever.redacted_input == "redacted query"
    assert rebuilt_retriever.redacted_output[0].content == "redacted document"
    assert rebuilt_retriever.metrics.duration_ns == 5
    assert isinstance(rebuilt_trace, Trace)
    assert rebuilt_trace.redacted_input == "redacted input"
    assert rebuilt_trace.redacted_output == "redacted output"
    assert rebuilt_trace.metrics.duration_ns == 6
    assert isinstance(rebuilt_session, Session)
    assert rebuilt_session.redacted_input[0].content == "redacted input"
    assert rebuilt_session.redacted_output[0].content == "redacted output"
    assert rebuilt_session.metrics.duration_ns == 7


def test_trace_public_content_parts_are_not_reserialized() -> None:
    source = Trace(
        input=[{"type": "text", "text": "input"}],
        output=[{"type": "text", "text": "output"}],
        redacted_input=[{"type": "text", "text": "redacted input"}],
        redacted_output=[{"type": "text", "text": "redacted output"}],
        spans=[],
    )

    rebuilt = Trace.model_validate(source.model_dump(mode="json", exclude_none=True))

    assert isinstance(rebuilt, Trace)
    assert rebuilt.model_dump(mode="json", exclude_none=True) == source.model_dump(
        mode="json", exclude_none=True
    )

    file_source = Trace(
        input=[{"type": "file", "file_id": str(uuid4())}],
        output=[{"type": "file", "file_id": str(uuid4())}],
        spans=[],
    )
    file_rebuilt = Trace.model_validate(file_source.model_dump(mode="json", exclude_none=True))
    assert isinstance(file_rebuilt, Trace)
    assert file_rebuilt.model_dump(mode="json", exclude_none=True) == file_source.model_dump(
        mode="json", exclude_none=True
    )


def test_malformed_trace_content_parts_follow_sdk_serialization() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Trace.model_validate({"input": "input", "output": [1], "spans": []})
    with pytest.raises(ValidationError):
        Trace.model_validate(
            {
                "input": "input",
                "output": [{"type": "file", "file_id": "not-a-uuid"}],
                "spans": [],
            }
        )


def test_context_hierarchy_fields_are_rejected_and_metadata_remains_supported() -> None:
    for hierarchy_field in ("children", "spans", "traces"):
        with pytest.raises(RecordFactoryError, match="Step.context cannot define.*Step.children"):
            record_from_step(
                Step(
                    type="tool",
                    name="tool",
                    input={"q": "input"},
                    context={hierarchy_field: []},
                )
            )
    metadata_record = record_from_step(
        Step(
            type="tool",
            name="tool",
            input={"q": "input"},
            context={"metadata": {"provider": "test"}, "request_id": "abc"},
        )
    )
    assert isinstance(metadata_record, ToolSpan)
    assert metadata_record.user_metadata == {"provider": "test"}


def test_trace_structured_values_are_normalized_without_losing_messages() -> None:
    trace_input = {"question": "hello"}
    trace_output = [{"role": "assistant", "content": "answer"}]
    record = record_from_step(
        Step(
            type="trace",
            name="request",
            input=trace_input,
            output=trace_output,
            children=[],
        )
    )

    assert isinstance(record, Trace)
    assert record.input == json.dumps(trace_input)
    assert [block.text for block in record.output] == ["answer"]


def test_trace_content_blocks_preserve_text_files_and_unrepresentable_data() -> None:
    file_id = uuid4()
    blocks = [
        {"type": "text", "text": "look at this"},
        {"type": "file", "file_id": str(file_id)},
    ]
    trace = record_from_step(
        Step(
            type="trace",
            name="multimodal",
            input=blocks,
            output=blocks,
            children=[],
        )
    )
    serialized_data_block = {
        "type": "data",
        "modality": "image",
        "url": "https://example/image.png",
    }
    data_trace = record_from_step(
        Step(
            type="trace",
            name="inline-image",
            input=[serialized_data_block],
            output=[serialized_data_block],
            children=[],
        )
    )

    assert isinstance(trace, Trace)
    assert isinstance(trace.input[0], TextContentPart)
    assert isinstance(trace.input[1], FileContentPart)
    assert trace.input[1].file_id == file_id
    assert isinstance(trace.output[0], TextContentPart)
    assert isinstance(trace.output[1], FileContentPart)
    assert isinstance(data_trace, Trace)
    assert json.loads(data_trace.input) == [serialized_data_block]
    assert json.loads(data_trace.output or "") == [serialized_data_block]


def test_trace_message_sequences_flatten_every_text_and_content_part() -> None:
    file_id = uuid4()
    output = [
        {"role": "assistant", "content": "first message"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "second message"},
                {"type": "file", "file_id": str(file_id)},
            ],
        },
    ]

    trace = record_from_step(
        Step(type="trace", name="messages", input="question", output=output, children=[])
    )

    assert isinstance(trace, Trace)
    assert [part.text for part in trace.output if isinstance(part, TextContentPart)] == [
        "first message",
        "second message",
    ]
    file_parts = [part for part in trace.output if isinstance(part, FileContentPart)]
    assert len(file_parts) == 1
    assert file_parts[0].file_id == file_id


def test_record_normalizer_defines_none_and_empty_value_behavior() -> None:
    assert GalileoRecordNormalizer.llm_input(None) == ""
    assert GalileoRecordNormalizer.llm_output(None) == ""
    assert GalileoRecordNormalizer.tool_input(None) == ""
    assert GalileoRecordNormalizer.tool_output(None) is None
    assert GalileoRecordNormalizer.retriever_output(None)[0].content == ""
    assert GalileoRecordNormalizer.retriever_output([]) == []
    assert GalileoRecordNormalizer.trace_input(None) == ""
    assert GalileoRecordNormalizer.trace_output(None) is None
    assert GalileoRecordNormalizer.trace_output([]) == []
    assert GalileoRecordNormalizer.session_input(None) is None
    assert GalileoRecordNormalizer.session_output(None) is None
    assert GalileoRecordNormalizer.session_input([]) == []
    assert GalileoRecordNormalizer.session_output([]) == []


def test_session_content_parts_are_preserved_by_input_and_output_normalizers() -> None:
    parts = [TextContentPart(text="text"), FileContentPart(file_id=uuid4())]

    assert GalileoRecordNormalizer.session_input(parts) == [
        part.model_dump(mode="json") for part in parts
    ]
    assert GalileoRecordNormalizer.session_output(parts) == [
        part.model_dump(mode="json") for part in parts
    ]


def test_session_output_serializes_unsupported_sequences_for_core_model() -> None:
    output = GalileoRecordNormalizer.session_output([1, 2])

    assert isinstance(output, str)
    assert output == json.dumps([1, 2])
    assert json.loads(output) == [1, 2]
    session = Session(input=[], output=output, traces=[])
    assert session.output == output


def test_record_normalizer_serializes_nested_models_uuids_and_timestamps() -> None:
    identifier = uuid4()
    timestamp = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)

    class NestedPayload(BaseModel):
        identifier: object
        timestamp: datetime

    payload = {
        "nested": {"answer": "42"},
        "payload": NestedPayload(identifier=identifier, timestamp=timestamp),
        "uuid": identifier,
        "timestamp": timestamp,
    }
    serialized = GalileoRecordNormalizer.tool_output(payload)

    assert serialized == (
        '{"nested": {"answer": "42"}, "payload": {"identifier": "'
        + str(identifier)
        + '", "timestamp": "2025-01-02T03:04:05Z"}, "uuid": "'
        + str(identifier)
        + '", "timestamp": "2025-01-02T03:04:05Z"}'
    )


def test_json_normalization_supports_python_value_types_and_fallbacks() -> None:
    from agent_control_evaluator_galileo.records.normalization import (
        _GalileoJSONEncoder,
        _json_compatible,
        _sdk_json_value,
    )

    class State(Enum):
        READY = "ready"

    class NestedModel(BaseModel):
        value: int
        optional: str | None = None

    class NestedValuesModel(BaseModel):
        payload: object

    @dataclass
    class NestedDataclass:
        identifier: object

    class SlottedValue:
        __slots__ = ("value", "missing")

        def __init__(self) -> None:
            self.value = "slot"

    class PlainValue:
        def __init__(self) -> None:
            self.visible = "public"
            self._hidden = "private"

    encoder = _GalileoJSONEncoder()
    identifier = uuid4()
    utc_timestamp = datetime(2025, 1, 2, tzinfo=UTC)
    naive_timestamp = datetime(2025, 1, 2)
    offset_timestamp = datetime(2025, 1, 2, tzinfo=timezone(timedelta(hours=2)))

    class StructuredState(Enum):
        VALUE = {"identifier": identifier, "timestamp": utc_timestamp}

    assert encoder.default(NestedModel(value=3)) == {"value": 3}
    assert encoder.default(utc_timestamp) == "2025-01-02T00:00:00Z"
    expected_naive_timestamp = naive_timestamp.astimezone()
    expected_naive_serialized = expected_naive_timestamp.isoformat()
    if expected_naive_timestamp.tzname() == UTC.tzname(None):
        expected_naive_serialized = expected_naive_serialized.replace("+00:00", "Z")
    assert encoder.default(naive_timestamp) == expected_naive_serialized
    assert encoder.default(offset_timestamp) == "2025-01-02T00:00:00+02:00"
    assert encoder.default(date(2025, 1, 2)) == "2025-01-02"
    assert encoder.default(identifier) == str(identifier)
    assert encoder.default(Path("folder/file.txt")) == "folder/file.txt"
    assert encoder.default(State.READY) == "ready"
    assert json.dumps(StructuredState.VALUE, cls=_GalileoJSONEncoder) == json.dumps(
        {"identifier": str(identifier), "timestamp": "2025-01-02T00:00:00Z"}
    )
    assert encoder.default(b"text") == "text"
    assert encoder.default(b"\xff") == "<not serializable bytes>"
    assert encoder.default(NestedDataclass(identifier)) == {"identifier": identifier}
    assert encoder.default({"item"}) == ["item"]
    assert encoder.default(object()) == "<object>"

    assert GalileoRecordNormalizer.json_text(42) == "42"
    assert GalileoRecordNormalizer.json_text(2**53) == json.dumps(str(2**53))
    assert GalileoRecordNormalizer.json_text({"large_integer": 2**53}) == json.dumps(
        {"large_integer": str(2**53)}
    )

    recursive: list[object] = []
    recursive.append(recursive)
    normalized = _sdk_json_value(
        {
            identifier: NestedModel(value=4),
            "date": date(2025, 1, 2),
            "enum": State.READY,
            "bytes": b"text",
            "invalid_bytes": b"\xff",
            "large_integer": 2**53,
            "set": frozenset({"item"}),
            "dataclass": NestedDataclass(identifier),
            "slotted": SlottedValue(),
            "plain": PlainValue(),
            "unsupported": object(),
            "recursive": recursive,
        }
    )
    assert normalized[str(identifier)] == {"value": 4}
    assert normalized["date"] == "2025-01-02"
    assert normalized["enum"] == "ready"
    assert normalized["bytes"] == "text"
    assert normalized["invalid_bytes"] == "<not serializable bytes>"
    assert normalized["large_integer"] == str(2**53)
    assert normalized["set"] == ["item"]
    assert normalized["dataclass"] == {"identifier": str(identifier)}
    assert normalized["slotted"] == {"value": "slot", "missing": None}
    assert normalized["plain"] == {"visible": "public"}
    assert normalized["unsupported"] == "<object>"
    assert normalized["recursive"] == ["list"]
    assert _json_compatible(NestedModel(value=5)) == {"value": 5}
    assert _json_compatible({"values": [State.READY, date(2025, 1, 2)]}) == {
        "values": ["ready", "2025-01-02"]
    }
    nested_values = _json_compatible(
        {
            "nested": {
                "set": {b"bytes"},
                "frozenset": frozenset({Path("nested/path")}),
                "invalid_bytes": {b"\xff"},
            },
            "model": NestedValuesModel(
                payload={"set": {b"model bytes"}, "path": Path("model/path")}
            ),
        }
    )
    assert nested_values == {
        "nested": {
            "set": ["bytes"],
            "frozenset": ["nested/path"],
            "invalid_bytes": ["<not serializable bytes>"],
        },
        "model": {"payload": {"set": ["model bytes"], "path": "model/path"}},
    }
    assert json.loads(json.dumps(nested_values)) == nested_values


def test_normalizer_preserves_message_content_and_reports_invalid_trace_inputs() -> None:
    from agent_control_evaluator_galileo.records.normalization import (
        _flatten_message_sequence,
        _message_content,
        _message_sequence,
        _normalize_content_items,
    )

    messages = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": ["plain", {"unsupported": True}]},
    ]
    flattened = _flatten_message_sequence(messages)

    assert [part["text"] for part in flattened] == [
        "plain",
        '{"unsupported": true}',
    ]
    assert _message_sequence([{"role": "user", "content": "question"}])
    assert not _message_sequence([{"content": "question"}])
    retriever_document = {"content": "retrieved text", "metadata": {"source": "kb"}}
    assert not _message_sequence([retriever_document])
    assert _message_content(retriever_document) is None
    assert not _message_sequence([{"other": "field"}])
    assert _normalize_content_items("not a sequence") is None
    assert _normalize_content_items([{"invalid": True}]) is None
    assert GalileoRecordNormalizer.llm_input(42) == "42"
    assert GalileoRecordNormalizer.llm_output([1, 2]) == "[1, 2]"
    with pytest.raises(TypeError, match="Trace input must be"):
        GalileoRecordNormalizer.trace_input([1])
    with pytest.raises(TypeError, match="does not support int"):
        GalileoRecordNormalizer.trace_input(1)


def test_retriever_and_session_normalizers_accept_public_models() -> None:
    class DocumentModel(BaseModel):
        content: str
        metadata: dict[str, str] = Field(default_factory=dict)

    pydantic_document = DocumentModel(content="model document")
    document = Document(content="canonical document")
    part = TextContentPart(text="content part")
    message = Message(role="user", content="question")

    assert GalileoRecordNormalizer.retriever_output(pydantic_document) == [
        Document(content="model document", metadata={})
    ]
    assert GalileoRecordNormalizer.retriever_output([pydantic_document]) == [
        Document(content="model document", metadata={})
    ]
    assert GalileoRecordNormalizer.retriever_output([document]) == [document]
    assert GalileoRecordNormalizer.session_input(part) == [part]
    assert GalileoRecordNormalizer.session_input(document) == '{"content": "canonical document"}'
    assert GalileoRecordNormalizer.session_input(pydantic_document) is pydantic_document
    assert GalileoRecordNormalizer.session_input({"role": "user", "content": "question"}) == {
        "role": "user",
        "content": "question",
    }
    assert GalileoRecordNormalizer.session_input({"type": "text", "text": "hello"}) == [
        {"type": "text", "text": "hello"}
    ]
    assert GalileoRecordNormalizer.session_input([message]) == [message]
    assert GalileoRecordNormalizer.session_input([{"role": "user", "content": "question"}]) == [
        {"role": "user", "content": "question"}
    ]
    assert json.loads(GalileoRecordNormalizer.session_input([pydantic_document]))[0][
        "content"
    ] == "model document"
    assert GalileoRecordNormalizer.session_output(document) == [document]
    assert GalileoRecordNormalizer.session_output(part) == [part]
    assert GalileoRecordNormalizer.session_output(pydantic_document) is pydantic_document
    assert GalileoRecordNormalizer.session_output({"role": "assistant", "content": "answer"}) == {
        "role": "assistant",
        "content": "answer",
    }
    assert GalileoRecordNormalizer.session_output({"page_content": "page"}).content == "page"
    assert GalileoRecordNormalizer.session_output({"type": "text", "text": "hello"}) == [
        {"type": "text", "text": "hello"}
    ]
    assert GalileoRecordNormalizer.session_output([document]) == [document]
    assert GalileoRecordNormalizer.session_output([{"role": "assistant", "content": "answer"}]) == [
        {"type": "text", "text": "answer"}
    ]


def test_llm_tool_definitions_normalize_nested_pydantic_uuid_and_datetime_values() -> None:
    identifier = uuid4()
    timestamp = datetime(2025, 1, 2, tzinfo=UTC)
    normalized_tools = GalileoRecordNormalizer.llm_tools(
        [{"id": identifier, "created_at": timestamp}]
    )
    record = LlmSpan.model_validate({"input": "question", "tools": normalized_tools})

    assert isinstance(record, LlmSpan)
    assert record.tools == [
        {"id": str(identifier), "created_at": timestamp.isoformat().replace("+00:00", "Z")}
    ]


def test_retriever_dictionaries_become_canonical_documents() -> None:
    documents = GalileoRecordNormalizer.retriever_output(
        [{"content": "document", "metadata": {"source": "kb"}}]
    )

    assert len(documents) == 1
    assert isinstance(documents[0], Document)
    assert documents[0].content == "document"
    assert documents[0].metadata == {"source": "kb"}


def test_trace_and_session_use_children_and_selectors_only_change_the_root() -> None:
    trace = record_from_step(
        Step(
            type="trace",
            name="outer",
            input="base question",
            children=[
                Step(
                    type="tool",
                    name="child",
                    input={"query": "child query"},
                    output="child result",
                    context={"metadata": {"owner": "child"}},
                ),
                Step(
                    type="llm",
                    name="child llm",
                    input="child prompt",
                    output="child response",
                    tools=[{"name": "lookup"}],
                )
            ],
        ),
        selected_data={"input": "selected question", "output": "selected answer"},
    )
    session = record_from_step(
        Step(
            type="session",
            name="conversation",
            input="base session",
            children=[
                Step(
                    type="trace",
                    name="child trace",
                    input="child question",
                    children=[Step(type="llm", name="child llm", input="child input")],
                )
            ],
        )
    )

    assert isinstance(trace, Trace)
    assert trace.input == "selected question"
    assert trace.output == "selected answer"
    assert isinstance(trace.spans[0], ToolSpan)
    assert json.loads(trace.spans[0].input) == {"query": "child query"}
    assert trace.spans[0].output == "child result"
    assert trace.spans[0].user_metadata == {"owner": "child"}
    assert isinstance(trace.spans[1], LlmSpan)
    assert trace.spans[1].tools == [{"name": "lookup"}]
    assert trace.spans[1].output.content == "child response"
    assert isinstance(session, Session)
    assert session.traces[0].name == "child trace"
    assert session.traces[0].input == "child question"
    assert isinstance(session.traces[0].spans[0], LlmSpan)


def test_children_must_be_valid_for_parent_and_trace_session_children_are_required() -> None:
    with pytest.raises(RecordFactoryError, match="cannot contain 'session'"):
        record_from_step(
            Step(type="trace", name="trace", input="q", children=[
                Step(type="session", name="session", input="q", children=[])
            ])
        )
    with pytest.raises(RecordFactoryError, match="cannot contain 'tool'"):
        record_from_step(
            Step(type="session", name="session", input="q", children=[
                Step(type="tool", name="tool", input={})
            ])
        )
    with pytest.raises(RecordFactoryError, match="missing Step.children"):
        record_from_step(
            Step(type="trace", name="trace", input={"input": "q", "spans": []})
        )
    with pytest.raises(RecordFactoryError, match="missing Step.children"):
        record_from_step(
            Step(type="session", name="session", input={"input": "q", "traces": []})
        )


def test_nested_tool_and_retriever_children_are_recursively_converted() -> None:
    record = record_from_step(
        Step(
            type="tool",
            name="outer",
            input={},
            children=[
                Step(
                    type="retriever",
                    name="inner retriever",
                    input="query",
                    output=["document"],
                    children=[Step(type="tool", name="leaf tool", input={"x": 1})],
                )
            ],
        )
    )

    assert isinstance(record, ToolSpan)
    retriever = record.spans[0]
    assert isinstance(retriever, RetrieverSpan)
    assert retriever.output[0].content == "document"
    assert isinstance(retriever.spans[0], ToolSpan)
    assert json.loads(retriever.spans[0].input) == {"x": 1}


def test_trace_missing_output_stays_none() -> None:
    record = record_from_step(
        Step(type="trace", name="request", input="question", children=[])
    )

    assert isinstance(record, Trace)
    assert record.output is None


def test_optional_fields_and_aliases_are_translated() -> None:
    llm = record_from_step(
        Step(
            type="llm",
            name="answer",
            input="question",
            tools=[{"name": "search"}],
        )
    )
    tool = ToolSpan.model_validate({"tool_call_id": "123"})
    alias = build_galileo_record("question", Step(type="llm", name="answer", input="base"))

    assert isinstance(llm, LlmSpan)
    assert llm.tools == [{"name": "search"}]
    assert isinstance(tool, ToolSpan)
    assert tool.tool_call_id == "123"
    assert isinstance(alias, LlmSpan)


def test_session_message_and_document_sequences_use_public_validators() -> None:
    messages = [{"role": "user", "content": "question"}]
    documents = [{"content": "answer", "metadata": {"source": "kb"}}]

    record = record_from_step(
        Step(
            type="session",
            name="conversation",
            input=messages,
            output=documents,
            children=[Step(type="trace", name="request", input="question", children=[])],
        )
    )

    assert isinstance(record, Session)
    assert [message.content for message in record.input] == ["question"]
    assert [document.model_dump() for document in record.output] == [
        {"content": "answer", "metadata": {"source": "kb"}}
    ]
    assert [trace.name for trace in record.traces] == ["request"]
    expected = Session(
        input=messages,
        output=documents,
        traces=[Trace(name="request", input="question", spans=[])],
    )
    assert type(record) is type(expected)
    assert [message.content for message in record.input] == [
        message.content for message in expected.input
    ]
    assert [document.model_dump() for document in record.output] == [
        document.model_dump() for document in expected.output
    ]


def test_trace_and_session_require_children_and_selector_values_must_be_structured() -> None:
    with pytest.raises(RecordFactoryError, match="missing Step.children"):
        record_from_step(Step(type="trace", name="request", input="question"))
    with pytest.raises(RecordFactoryError, match="missing Step.children"):
        record_from_step(Step(type="session", name="conversation", input="question"))
    with pytest.raises(RecordFactoryError, match="untyped scalar"):
        build_record(
            "question",
            Step(type="trace", name="request", input="question", children=[]),
        )


def test_unsupported_step_type_is_explicit() -> None:
    with pytest.raises(UnsupportedStepTypeError, match="custom"):
        record_from_step(Step(type="custom", name="custom", input="value"))


def test_record_serialization_is_json_safe() -> None:
    record = record_from_step(Step(type="tool", name="search", input={"q": "x"}))

    payload = record.model_dump(mode="json", exclude_none=True)

    assert payload["type"] == "tool"
    assert payload["input"] == json.dumps({"q": "x"})


def test_public_core_model_validates_luna_request_record_payload() -> None:
    from agent_control_evaluator_galileo.luna import ScorerInvokeRecord

    source = ToolSpan(name="search", input=json.dumps({"query": "q"}))
    request_record = ScorerInvokeRecord.model_validate(
        source.model_dump(mode="json", exclude_none=True)
    )
    record = ToolSpan.model_validate(request_record.model_dump(mode="json", exclude_none=True))

    assert record == source


def test_canonical_records_round_trip_through_luna_wire_model() -> None:
    from agent_control_evaluator_galileo.luna import ScorerInvokeRecord

    llm_step = Step(
        type="llm",
        name="answer",
        input=[{"role": "user", "content": "question"}],
        output="answer",
        tools=[{"name": "lookup"}],
        context={"metadata": {"source": "llm"}},
    )
    nested_tool = Step(
        type="tool",
        name="search",
        input={"query": "q"},
        output="result",
        context={"metadata": {"source": "tool"}},
        children=[llm_step],
    )
    records = [
        (
            llm_step,
            LlmSpan,
        ),
        (
            Step(type="tool", name="flat tool", input={"id": 1}, output="done"),
            ToolSpan,
        ),
        (
            Step(
                type="retriever",
                name="retrieve",
                input="query",
                output=[{"content": "document", "metadata": {"source": "kb"}}],
            ),
            RetrieverSpan,
        ),
        (
            Step(
                type="trace",
                name="trace",
                input="trace input",
                output="trace output",
                children=[nested_tool],
            ),
            Trace,
        ),
        (
            Step(
                type="session",
                name="session",
                input="session input",
                output="session output",
                children=[
                    Step(
                        type="trace",
                        name="session trace",
                        input="trace input",
                        children=[
                            Step(
                                type="tool",
                                name="session tool",
                                input={"query": "session query"},
                                output="session result",
                            )
                        ],
                    )
                ],
            ),
            Session,
        ),
    ]

    for step, core_model in records:
        canonical = record_from_step(step)
        wire_json = canonical.model_dump(mode="json", exclude_none=True)
        request_record = ScorerInvokeRecord.model_validate(wire_json)
        reconstructed = core_model.model_validate(
            request_record.model_dump(mode="json", exclude_none=True)
        )

        assert type(reconstructed) is type(canonical)
        assert reconstructed.model_dump(mode="json", exclude_none=True) == wire_json

    trace = record_from_step(records[3][0])
    assert isinstance(trace, Trace)
    assert isinstance(trace.spans[0], ToolSpan)
    assert isinstance(trace.spans[0].spans[0], LlmSpan)
    assert trace.spans[0].user_metadata == {"source": "tool"}
    assert trace.spans[0].spans[0].tools == [{"name": "lookup"}]

    session = record_from_step(records[4][0])
    assert isinstance(session, Session)
    assert isinstance(session.traces[0], Trace)
    assert isinstance(session.traces[0].spans[0], ToolSpan)


def test_luna_wire_hierarchy_uses_top_level_fields_not_context() -> None:
    from agent_control_evaluator_galileo.luna import ScorerInvokeRecord
    from pydantic import ValidationError

    canonical_trace = record_from_step(
        Step(
            type="trace",
            name="canonical trace",
            input="trace input",
            children=[Step(type="tool", name="canonical tool", input={})],
        )
    )
    canonical_session = record_from_step(
        Step(
            type="session",
            name="canonical session",
            input="session input",
            children=[
                Step(type="trace", name="canonical child trace", input="trace input", children=[])
            ],
        )
    )
    trace_payload = canonical_trace.model_dump(mode="json", exclude_none=True)
    session_payload = canonical_session.model_dump(mode="json", exclude_none=True)
    assert "spans" in trace_payload
    assert "traces" in session_payload
    assert "context" not in trace_payload
    assert "context" not in session_payload

    wire_trace = ScorerInvokeRecord.model_validate(
        {
            "type": "trace",
            "name": "trace",
            "input": "trace input",
            "spans": [{"type": "tool", "name": "wire tool", "input": "{}"}],
            "context": {
                "children": [{"type": "llm", "name": "ignored child"}],
                "spans": [{"type": "llm", "name": "ignored span"}],
                "traces": [{"type": "trace", "name": "ignored trace"}],
            },
        }
    )
    wire_trace_json = wire_trace.model_dump(mode="json", exclude_none=True)
    try:
        rebuilt_trace = Trace.model_validate(wire_trace_json)
    except ValidationError as exc:
        assert any("context" in error["loc"] for error in exc.errors())
    else:
        assert len(rebuilt_trace.spans) == 1
        assert isinstance(rebuilt_trace.spans[0], ToolSpan)
        assert rebuilt_trace.spans[0].name == "wire tool"
        assert all(span.name != "ignored span" for span in rebuilt_trace.spans)

    # Galileo Core supplies empty hierarchy defaults when top-level fields are absent.
    # Context-only hierarchy must not be treated as canonical spans or traces.
    context_only_trace = ScorerInvokeRecord.model_validate(
        {
            "type": "trace",
            "name": "context only trace",
            "context": {
                "children": [{"type": "tool", "name": "ignored child"}],
                "spans": [{"type": "tool", "name": "ignored span"}],
            },
        }
    )
    rebuilt_context_only_trace = Trace.model_validate(
        context_only_trace.model_dump(mode="json", exclude_none=True)
    )
    assert rebuilt_context_only_trace.spans == []

    context_only_session = ScorerInvokeRecord.model_validate(
        {
            "type": "session",
            "name": "session",
            "context": {"traces": [{"type": "trace", "name": "ignored trace"}]},
        }
    )
    context_only_json = context_only_session.model_dump(mode="json", exclude_none=True)
    rebuilt_context_only_session = Session.model_validate(context_only_json)
    assert rebuilt_context_only_session.traces == []


def test_luna_wire_round_trip_preserves_all_trace_span_types_and_nested_tool_span() -> None:
    from agent_control_evaluator_galileo.luna import ScorerInvokeRecord

    trace_step = Step(
        type="trace",
        name="trace",
        input="question",
        children=[
            Step(type="llm", name="answer", input="question", output="answer"),
            Step(type="tool", name="search", input={"query": "q"}, output="result"),
            Step(
                type="retriever",
                name="retrieve",
                input="query",
                output=[{"content": "document"}],
            ),
        ],
    )
    tool_step = Step(
        type="tool",
        name="outer tool",
        input={"query": "q"},
        children=[Step(type="llm", name="inner llm", input="tool prompt")],
    )

    for step, core_model in ((trace_step, Trace), (tool_step, ToolSpan)):
        canonical = record_from_step(step)
        wire_json = canonical.model_dump(mode="json", exclude_none=True)
        request_record = ScorerInvokeRecord.model_validate(wire_json)
        reconstructed = core_model.model_validate(
            request_record.model_dump(mode="json", exclude_none=True)
        )

        assert type(reconstructed) is type(canonical)
        assert reconstructed.model_dump(mode="json", exclude_none=True) == wire_json

    trace = record_from_step(trace_step)
    assert isinstance(trace, Trace)
    assert [type(span) for span in trace.spans] == [LlmSpan, ToolSpan, RetrieverSpan]

    tool = record_from_step(tool_step)
    assert isinstance(tool, ToolSpan)
    assert isinstance(tool.spans[0], LlmSpan)
    assert tool.spans[0].name == "inner llm"


@pytest.mark.parametrize(
    ("payload", "core_model"),
    [
        (
            {
                "type": "session",
                "name": "session",
                "traces": [{"type": "tool", "name": "invalid child"}],
            },
            Session,
        ),
        (
            {
                "type": "trace",
                "name": "trace",
                "spans": [{"type": "session", "name": "invalid child", "traces": []}],
            },
            Trace,
        ),
    ],
)
def test_luna_wire_records_reject_invalid_hierarchy(
    payload: dict[str, object],
    core_model: type[BaseModel],
) -> None:
    from agent_control_evaluator_galileo.luna import ScorerInvokeRecord
    from pydantic import ValidationError

    request_record = ScorerInvokeRecord.model_validate(payload)

    with pytest.raises(ValidationError):
        core_model.model_validate(request_record.model_dump(mode="json", exclude_none=True))


def test_factory_rejects_invalid_boundaries_and_normalizes_missing_text() -> None:
    from agent_control_evaluator_galileo.records import GalileoRecordNormalizer

    with pytest.raises(RecordFactoryError, match="complete Agent Control Step"):
        record_from_step(object())  # type: ignore[arg-type]
    assert GalileoRecordNormalizer.retriever_input(None) == ""
    assert GalileoRecordNormalizer.session_input(Document(content="plain")) == json.dumps(
        {"content": "plain"}
    )
    assert GalileoRecordNormalizer.session_input([Document(content="plain")]) == json.dumps(
        [{"content": "plain"}]
    )
