"""Tests for optional structured runtime context on Step."""

from agent_control_models import Step
from pydantic import ValidationError


def test_step_accepts_and_serializes_structured_tools_and_ground_truth() -> None:
    # Given: a runtime LLM step with structured scorer context
    payload = {
        "type": "llm",
        "name": "answer",
        "input": {"question": "Capital of France?"},
        "output": "Paris",
        "tools": [
            {
                "name": "search",
                "description": "Search documents",
                "input_schema": {"type": "object"},
            }
        ],
        "ground_truth": {"answer": "Paris"},
    }

    # When: validating and serializing the public Step model
    serialized = Step.model_validate(payload).model_dump(mode="json")

    # Then: structured values survive unchanged
    assert serialized["tools"] == payload["tools"]
    assert serialized["ground_truth"] == payload["ground_truth"]


def test_existing_step_payload_remains_valid() -> None:
    # Given/When: an existing payload without structured context
    step = Step(type="llm", name="answer", input="hello")

    # Then: new fields remain optional
    assert step.tools is None
    assert step.ground_truth is None


def test_step_is_immutable_runtime_context() -> None:
    # Given: a validated runtime step
    step = Step(type="llm", name="answer", input="hello")

    # When/Then: evaluators cannot replace request-scoped fields
    try:
        step.input = "changed"
    except ValidationError:
        pass
    else:
        raise AssertionError("Step must be frozen")


def test_step_preserves_recursive_execution_evidence() -> None:
    """Documents, tool calls, outcomes, children, and history stay distinct."""
    child = {
        "type": "tool",
        "name": "search",
        "input": {"query": "agent control"},
        "output": {"results": []},
        "status_code": 502,
    }
    step = Step(
        type="llm",
        name="answer",
        input="question",
        documents=[{"content": "reference", "id": "doc-1", "metadata": {"rank": 1}}],
        tool_calls=[{"id": "call-1", "name": "search", "arguments": {"query": "agent control"}}],
        status_code=200,
        children=[child],
        history=[child],
    )

    assert step.documents is not None
    assert step.documents[0].content == "reference"
    assert step.tool_calls is not None
    assert step.tool_calls[0].arguments == {"query": "agent control"}
    assert step.children is not step.history
    assert step.children is not None and step.children[0].status_code == 502
    assert step.history is not None and step.history[0].status_code == 502
