"""Tests for framework-neutral available-tool normalization."""

import pytest

from agent_control.integrations._tools import normalize_strands_tool_specs


@pytest.mark.parametrize(
    "specs",
    [
        {"search": {}},
        ["not-a-tool-spec"],
        [{"description": "missing name"}],
        [{"name": ""}],
    ],
)
def test_normalizer_rejects_incomplete_strands_registries(specs: object) -> None:
    # Given/When: the purported complete registry has an invalid shape
    normalized = normalize_strands_tool_specs(specs)

    # Then: the integration leaves tools absent rather than guessing
    assert normalized is None


@pytest.mark.parametrize(
    ("input_schema", "expected"),
    [
        ({"type": "object", "properties": {}}, {"type": "object", "properties": {}}),
        (None, {}),
    ],
)
def test_normalizer_supports_plain_or_missing_strands_input_schema(
    input_schema: object,
    expected: dict[str, object],
) -> None:
    # Given: valid Strands specs from supported schema variants
    spec: dict[str, object] = {"name": "search", "description": 123}
    if input_schema is not None:
        spec["inputSchema"] = input_schema

    # When: normalizing the complete registry
    normalized = normalize_strands_tool_specs([spec])

    # Then: a stable JSON-only tool definition is produced
    assert normalized == [
        {"name": "search", "description": "", "input_schema": expected}
    ]
