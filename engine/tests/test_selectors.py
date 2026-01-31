"""Tests for data selectors."""
from typing import Any

import pytest
from agent_control_engine.selectors import select_data
from agent_control_models import Step


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
