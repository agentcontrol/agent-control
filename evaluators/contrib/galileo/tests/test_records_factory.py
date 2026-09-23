"""Tests for the shared Agent Control to Galileo record factory."""

from __future__ import annotations

import json

import pytest
from agent_control_evaluator_galileo.records import (
    RecordFactoryError,
    UnsupportedStepTypeError,
    build_record,
    record_from_scorer_invoke_record,
    record_from_step,
)
from agent_control_models import Step
from splunk_ao import Document, LlmSpan, Message, RetrieverSpan, Session, ToolSpan, Trace
from splunk_ao.utils.retrievers import convert_to_documents
from splunk_ao.utils.serialization import serialize_to_str


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


def test_trace_missing_output_stays_none() -> None:
    record = record_from_step(
        Step(type="trace", name="request", input="question", context={"spans": []})
    )

    assert isinstance(record, Trace)
    assert record.output is None


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
