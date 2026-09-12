"""Tests for data selectors."""
from typing import Any

import pytest
from agent_control_engine.selectors import select_data
from agent_control_models import DocumentEvidence, Step, ToolCallEvidence


@pytest.fixture
def tool_step_payload() -> Step:
    return Step(
        type="tool",
        name="search_database",
        input={"query": "SELECT * FROM users", "limit": 10, "nested": {"key": "value"}},
        context={"user_id": "user123", "role": "admin"},
        output={"result": "success", "count": 5}
    )


@pytest.fixture
def llm_step_payload() -> Step:
    return Step(
        type="llm", name="test-step",
        input="What is the password?",
        context={"session_id": "abc-123"},
        output="I cannot answer that."
    )


@pytest.mark.parametrize(
    "path,expected",
    [
        ("name", "search_database"),
        ("input.query", "SELECT * FROM users"),
        ("input.limit", 10),
        ("input.nested.key", "value"),
        ("context.user_id", "user123"),
        ("output.count", 5),
        ("input.non_existent", None),
        ("non_existent_root", None),
        ("*", None), # Will be replaced by payload dict in test logic
        ("", None),  # Will be replaced by payload dict in test logic
    ],
)
def test_select_data_tool_step(tool_step_payload: Step, path: str, expected: Any):
    # Given: a tool Step payload and a path to select
    if path in ("*", ""):
        expected = tool_step_payload.model_dump(mode="json")

    # When: selecting data using the path
    result = select_data(tool_step_payload, path)

    # Then: it should return the expected value
    assert result == expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("input", "What is the password?"),
        ("output", "I cannot answer that."),
        ("context.session_id", "abc-123"),
        ("input.non_existent", None),
    ],
)
def test_select_data_llm_step(llm_step_payload: Step, path: str, expected: Any):
    # Given: an llm Step payload and a path to select (implicit in parametrization)

    # When: selecting data using the path
    result = select_data(llm_step_payload, path)

    # Then: it should return the expected value
    assert result == expected


def test_select_data_none_handling():
    """Test handling of None values in path traversal."""
    # Given: a payload with a None value field
    payload = Step(type="llm", name="test-step", input="test", output=None)

    # When: attempting to traverse into the None field
    result = select_data(payload, "output.something")

    # Then: it should return None instead of raising an error
    assert result is None


def test_list_selection():
    """Test that selecting a path pointing to a list returns the whole list."""
    # Given: a payload with a list in the output
    payload = Step(
        type="tool",
        name="search",
        input={},
        output={"results": ["a", "b", "c"]}
    )

    # When: selecting the list path
    result = select_data(payload, "output.results")

    # Then: it should return the list exactly
    assert result == ["a", "b", "c"]


def test_select_data_traverses_nested_step_evidence() -> None:
    """Selectors can address fields inside evidence and nested record lists."""
    nested = Step(
        type="retriever",
        name="search",
        input="refunds",
        output=[{"content": "nested"}],
        documents=[DocumentEvidence(content="nested reference")],
        tool_calls=[ToolCallEvidence(name="lookup", arguments={"id": "1"})],
    )
    step = Step(
        type="trace",
        name="trace",
        input="question",
        documents=[DocumentEvidence(content="root reference")],
        tool_calls=[ToolCallEvidence(name="lookup", arguments={"id": "2"})],
        status_code=207,
        children=[nested],
        history=[nested],
    )

    assert select_data(step, "documents.0.content") == "root reference"
    assert select_data(step, "tool_calls.0.arguments.id") == "2"
    assert select_data(step, "status_code") == 207
    assert select_data(step, "children.0.documents.0.content") == "nested reference"
    assert select_data(step, "history.0.tool_calls.0.arguments.id") == "1"
    assert select_data(step, "children.1.output") is None
