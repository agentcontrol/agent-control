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
