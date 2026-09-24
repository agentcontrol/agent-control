"""Tests for the shared Agent Control to Galileo record factory."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_control_evaluator_galileo.records import (
    GalileoRecordNormalizer,
    RecordFactoryError,
    UnsupportedStepTypeError,
    build_galileo_record,
    build_record,
    record_from_scorer_invoke_record,
    record_from_step,
)
from agent_control_models import Step
from galileo_core.schemas.logging.llm import Message
from galileo_core.schemas.logging.session import Session
from galileo_core.schemas.logging.span import LlmSpan, RetrieverSpan, ToolSpan
from galileo_core.schemas.logging.trace import Trace
from galileo_core.schemas.shared.content_parts import FileContentPart, TextContentPart
from galileo_core.schemas.shared.document import Document
from pydantic import BaseModel, ConfigDict


class _RecordPayload(BaseModel):
    """Flexible Pydantic boundary model used to exercise the adapter contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    type: str
    name: str | None = None
    input: object | None = None
    output: object | None = None
    context: object | None = None
    spans: object | None = None
    traces: object | None = None
    tool_call_id: object | None = None


def test_required_galileo_core_public_exports_are_importable() -> None:
    assert all((LlmSpan, ToolSpan, RetrieverSpan, Trace, Session, Document, Message))


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
    from pydantic import BaseModel

    document = Document(content="context", metadata={"source": "kb"})

    class RecordInput(BaseModel):
        type: str = "retriever"
        name: str = "retrieve"
        input: str = "question"
        output: object

    record = record_from_scorer_invoke_record(RecordInput(output=document))

    assert isinstance(record, RetrieverSpan)
    assert record.output[0].content == "context"
    assert record.output[0].metadata == {"source": "kb"}


def test_public_document_metadata_variants_are_supported() -> None:
    document_without_metadata = Document(content="plain")
    document_with_model_metadata = Document.model_validate(
        {"content": "model metadata", "metadata": {"source": "kb"}}
    )

    record = record_from_scorer_invoke_record(
        _RecordPayload(
            type="retriever",
            input="question",
            output=[document_without_metadata, document_with_model_metadata],
        )
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
            context={
                "spans": [
                    {
                        "type": "tool",
                        "name": "search",
                        "input": {"q": "x"},
                        "spans": [{"type": "tool", "name": "nested", "input": {"q": "y"}}],
                    },
                    {"type": "retriever", "name": "retrieve", "input": "x", "output": []},
                ]
            },
        )
    )
    session = record_from_step(
        Step(
            type="session",
            name="conversation",
            input="question",
            context={"traces": [trace.model_dump(mode="json")]},
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

    rebuilt_llm = record_from_scorer_invoke_record(
        _RecordPayload(**llm_source.model_dump(mode="json", exclude_none=True))
    )
    rebuilt_tool = record_from_scorer_invoke_record(
        _RecordPayload(**tool_source.model_dump(mode="json", exclude_none=True))
    )
    rebuilt_retriever = record_from_scorer_invoke_record(
        _RecordPayload(**retriever_source.model_dump(mode="json", exclude_none=True))
    )
    rebuilt_trace = record_from_scorer_invoke_record(
        _RecordPayload(**trace_source.model_dump(mode="json", exclude_none=True))
    )
    rebuilt_session = record_from_scorer_invoke_record(
        _RecordPayload(**session_source.model_dump(mode="json", exclude_none=True))
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

    rebuilt = record_from_scorer_invoke_record(
        _RecordPayload(**source.model_dump(mode="json", exclude_none=True))
    )

    assert isinstance(rebuilt, Trace)
    assert rebuilt.model_dump(mode="json", exclude_none=True) == source.model_dump(
        mode="json", exclude_none=True
    )

    file_source = Trace(
        input=[{"type": "file", "file_id": str(uuid4())}],
        output=[{"type": "file", "file_id": str(uuid4())}],
        spans=[],
    )
    file_rebuilt = record_from_scorer_invoke_record(
        _RecordPayload(**file_source.model_dump(mode="json", exclude_none=True))
    )
    assert isinstance(file_rebuilt, Trace)
    assert file_rebuilt.model_dump(mode="json", exclude_none=True) == file_source.model_dump(
        mode="json", exclude_none=True
    )


def test_malformed_trace_content_parts_follow_sdk_serialization() -> None:
    scalar_item = record_from_scorer_invoke_record(
        _RecordPayload(type="trace", input="input", output=[1], spans=[])
    )
    invalid_file = record_from_scorer_invoke_record(
        _RecordPayload(
            type="trace",
            input="input",
            output=[{"type": "file", "file_id": "not-a-uuid"}],
            spans=[],
        )
    )

    assert isinstance(scalar_item, Trace)
    assert isinstance(invalid_file, Trace)
    assert scalar_item.output == json.dumps([1])
    assert invalid_file.output == json.dumps([{"type": "file", "file_id": "not-a-uuid"}])


def test_nested_record_errors_and_existing_models_are_explicit() -> None:
    from agent_control_evaluator_galileo.records.factory import _record_from_mapping

    existing_child = ToolSpan(name="existing", input="input")
    with pytest.raises(RecordFactoryError, match="objects"):
        record_from_scorer_invoke_record(
            _RecordPayload(type="tool", input="input", spans=[1])
        )
    with pytest.raises(RecordFactoryError, match="string 'type'"):
        record_from_scorer_invoke_record(
            _RecordPayload(type="tool", input="input", spans=[{}])
        )
    with pytest.raises(UnsupportedStepTypeError, match="custom"):
        record_from_scorer_invoke_record(
            _RecordPayload(type="tool", input="input", spans=[{"type": "custom"}])
        )
    with pytest.raises(RecordFactoryError, match="span record"):
        record_from_scorer_invoke_record(
            _RecordPayload(
                type="tool",
                input="input",
                spans=[{"type": "trace", "input": "input", "spans": []}],
            )
        )

    record = _record_from_mapping(
        {"type": "tool", "input": "input", "spans": [existing_child]}, "tool"
    )
    assert isinstance(record, ToolSpan)
    assert record.spans[0].name == existing_child.name


def test_invalid_nested_context_shapes_are_rejected() -> None:
    valid_context_record = record_from_step(
        Step(type="tool", name="tool", input={"q": "input"}, context={"spans": []})
    )
    children_context_record = record_from_step(
        Step(type="tool", name="tool", input={"q": "input"}, context={"children": []})
    )
    assert isinstance(valid_context_record, ToolSpan)
    assert isinstance(children_context_record, ToolSpan)
    with pytest.raises(RecordFactoryError, match="context must be a list"):
        record_from_step(
            Step(type="tool", name="tool", input={"q": "input"}, context={"spans": "invalid"})
        )
    with pytest.raises(RecordFactoryError, match="span context"):
        record_from_scorer_invoke_record(
            _RecordPayload(type="tool", input="input", spans="invalid")
        )
    with pytest.raises(RecordFactoryError, match="trace context"):
        record_from_scorer_invoke_record(_RecordPayload(type="trace", input="input"))
    with pytest.raises(RecordFactoryError, match="session context"):
        record_from_scorer_invoke_record(_RecordPayload(type="session", input="input"))
    with pytest.raises(RecordFactoryError, match="trace records"):
        record_from_scorer_invoke_record(
            _RecordPayload(type="session", input="input", traces=[{"type": "tool"}])
        )


def test_trace_structured_values_are_normalized_without_losing_messages() -> None:
    trace_input = {"question": "hello"}
    trace_output = [{"role": "assistant", "content": "answer"}]
    record = record_from_step(
        Step(
            type="trace",
            name="request",
            input=trace_input,
            output=trace_output,
            context={"spans": []},
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
            context={"spans": []},
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
            context={"spans": []},
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
        Step(type="trace", name="messages", input="question", output=output, context={"spans": []})
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


def test_llm_tool_definitions_normalize_nested_pydantic_uuid_and_datetime_values() -> None:
    identifier = uuid4()
    timestamp = datetime(2025, 1, 2, tzinfo=UTC)
    source = _RecordPayload(
        type="llm",
        input="question",
        tools=[{"id": identifier, "created_at": timestamp}],
    )

    record = record_from_scorer_invoke_record(source)

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


def test_trace_and_session_envelopes_are_supported() -> None:
    trace = record_from_step(
        Step(
            type="trace",
            name="outer",
            input={"input": "question", "spans": []},
        )
    )
    session = record_from_step(
        Step(
            type="session",
            name="outer",
            input={"input": "question", "traces": []},
        )
    )
    wrapped_trace = record_from_step(
        Step(
            type="trace",
            name="outer",
            input="ignored",
            context={"trace": {"name": "inner", "input": "question", "spans": []}},
        )
    )
    wrapped_session = record_from_step(
        Step(
            type="session",
            name="outer",
            input="ignored",
            context={"session": {"name": "inner", "input": "question", "traces": []}},
        )
    )
    selected_trace = record_from_step(
        Step(
            type="trace",
            name="outer",
            input="ignored",
            context={
                "trace": {
                    "name": "inner",
                    "input": "wrapped input",
                    "output": "wrapped output",
                    "spans": [],
                }
            },
        ),
        selected_data={"input": "selected input", "output": "selected output"},
    )
    selected_session = record_from_step(
        Step(
            type="session",
            name="outer",
            input="ignored",
            context={
                "session": {
                    "name": "inner",
                    "input": "wrapped input",
                    "output": "wrapped output",
                    "traces": [],
                }
            },
        ),
        selected_data={"input": "selected input", "output": "selected output"},
    )

    assert isinstance(trace, Trace)
    assert isinstance(session, Session)
    assert isinstance(wrapped_trace, Trace)
    assert isinstance(wrapped_session, Session)
    assert isinstance(selected_trace, Trace)
    assert isinstance(selected_session, Session)
    assert trace.input == "question"
    assert session.input == "question"
    assert wrapped_trace.name == "inner"
    assert wrapped_session.name == "inner"
    assert selected_trace.input == "selected input"
    assert selected_trace.output == "selected output"
    assert selected_session.input == "selected input"
    assert selected_session.output == "selected output"


def test_trace_missing_output_stays_none() -> None:
    record = record_from_step(
        Step(type="trace", name="request", input="question", context={"spans": []})
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
    tool = record_from_scorer_invoke_record(
        _RecordPayload(type="tool", input="input", tool_call_id=123)
    )
    alias = build_galileo_record("question", Step(type="llm", name="answer", input="base"))

    assert isinstance(llm, LlmSpan)
    assert llm.tools == [{"name": "search"}]
    assert isinstance(tool, ToolSpan)
    assert tool.tool_call_id == "123"
    assert isinstance(alias, LlmSpan)


def test_session_message_and_document_sequences_use_public_validators() -> None:
    traces = [{"type": "trace", "name": "request", "input": "question", "spans": []}]
    messages = [{"role": "user", "content": "question"}]
    documents = [{"content": "answer", "metadata": {"source": "kb"}}]

    record = record_from_step(
        Step(
            type="session",
            name="conversation",
            input=messages,
            output=documents,
            context={"traces": traces},
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


def test_trace_and_session_require_structured_context() -> None:
    with pytest.raises(RecordFactoryError, match="trace context is missing"):
        record_from_step(Step(type="trace", name="request", input="question"))
    with pytest.raises(RecordFactoryError, match="session context is missing"):
        record_from_step(Step(type="session", name="conversation", input="question"))
    with pytest.raises(RecordFactoryError, match="untyped scalar"):
        build_record(
            "question",
            Step(type="trace", name="request", input="question", context={"spans": []}),
        )


def test_unsupported_step_type_is_explicit() -> None:
    with pytest.raises(UnsupportedStepTypeError, match="custom"):
        record_from_step(Step(type="custom", name="custom", input="value"))


def test_record_serialization_is_json_safe() -> None:
    record = record_from_step(Step(type="tool", name="search", input={"q": "x"}))

    payload = record.model_dump(mode="json", exclude_none=True)

    assert payload["type"] == "tool"
    assert payload["input"] == json.dumps({"q": "x"})


def test_factory_accepts_the_existing_pydantic_luna_record() -> None:
    from agent_control_evaluator_galileo.luna import ScorerInvokeRecord

    record = record_from_scorer_invoke_record(
        ScorerInvokeRecord(type="tool", name="search", input={"query": "q"})
    )

    assert isinstance(record, ToolSpan)
    assert json.loads(record.input) == {"query": "q"}


def test_factory_rejects_invalid_boundaries_and_normalizes_missing_text() -> None:
    from agent_control_evaluator_galileo.records import GalileoRecordNormalizer

    with pytest.raises(RecordFactoryError, match="complete Agent Control Step"):
        record_from_step(object())  # type: ignore[arg-type]
    with pytest.raises(UnsupportedStepTypeError, match="unsupported"):
        record_from_scorer_invoke_record(_RecordPayload(type="unsupported"))
    assert GalileoRecordNormalizer.retriever_input(None) == ""
    assert GalileoRecordNormalizer.session_input(Document(content="plain")) == json.dumps(
        {"content": "plain"}
    )
    assert GalileoRecordNormalizer.session_input([Document(content="plain")]) == json.dumps(
        [{"content": "plain"}]
    )
