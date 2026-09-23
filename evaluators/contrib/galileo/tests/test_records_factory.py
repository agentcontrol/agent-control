"""Tests for the shared Agent Control to Galileo record factory."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from agent_control_evaluator_galileo.records import (
    RecordFactoryError,
    UnsupportedStepTypeError,
    build_galileo_record,
    build_record,
    record_from_scorer_invoke_record,
    record_from_step,
)
from agent_control_models import Step
from pydantic import BaseModel, ConfigDict
from splunk_ao import Document, LlmSpan, Message, RetrieverSpan, Session, ToolSpan, Trace
from splunk_ao.utils.retrievers import convert_to_documents
from splunk_ao.utils.serialization import serialize_to_str


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


def test_required_splunk_ao_public_exports_are_importable() -> None:
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
    assert record.dataset_output == serialize_to_str({"expected": "answer"})


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
    assert record.output.content == serialize_to_str(output)
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
        input=serialize_to_str({"query": "q"}),
        output=serialize_to_str({"hits": [1, 2]}),
    )
    assert type(record) is type(expected)
    assert record.input == expected.input
    assert record.output == expected.output


@pytest.mark.parametrize(
    "output",
    [None, "text", {"content": "document"}, {"invalid": True}, 42, ["one", "two"]],
)
def test_retriever_matches_sdk_document_coercion(output: object) -> None:
    expected = convert_to_documents(output)

    try:
        record = record_from_step(
            Step(type="retriever", name="retrieve", input="question", output=output)
        )
    except (TypeError, ValueError):
        with pytest.raises((TypeError, ValueError)):
            RetrieverSpan(input="question", output=expected)
        return

    assert isinstance(record, RetrieverSpan)
    assert [document.model_dump() for document in record.output] == [
        document.model_dump() for document in expected
    ]


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


def test_retriever_accepts_the_public_splunk_ao_document_model() -> None:
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
    document_with_model_metadata = Document.from_dict(
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


def test_trace_structured_values_match_sdk_logger_coercion() -> None:
    from splunk_ao import SplunkAOLogger

    trace_input = {"question": "hello"}
    trace_output = [{"role": "assistant", "content": "answer"}]
    expected_input = SplunkAOLogger._coerce_trace_input("input", trace_input)
    expected_output = SplunkAOLogger._coerce_output(trace_output)

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
    assert record.input == expected_input
    assert [block.text for block in record.output] == [block.text for block in expected_output]


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
    assert payload["input"] == serialize_to_str({"q": "x"})


def test_factory_accepts_the_existing_pydantic_luna_record() -> None:
    from agent_control_evaluator_galileo.luna import ScorerInvokeRecord

    record = record_from_scorer_invoke_record(
        ScorerInvokeRecord(type="tool", name="search", input={"query": "q"})
    )

    assert isinstance(record, ToolSpan)
    assert json.loads(record.input) == {"query": "q"}


def test_factory_rejects_invalid_boundaries_and_normalizes_missing_text() -> None:
    from agent_control_evaluator_galileo.records.normalization import session_value, text_value

    with pytest.raises(RecordFactoryError, match="complete Agent Control Step"):
        record_from_step(object())  # type: ignore[arg-type]
    with pytest.raises(UnsupportedStepTypeError, match="unsupported"):
        record_from_scorer_invoke_record(_RecordPayload(type="unsupported"))
    assert text_value(None) == ""
    assert session_value(Document(content="plain")) == {"content": "plain"}
    assert session_value([Document(content="plain")]) == [{"content": "plain"}]
