"""Tests for server-facing shared model contracts."""

from agent_control_models.server import ControlSource, ControlSummary, GetControlResponse


def test_control_response_source_is_optional_with_custom_default() -> None:
    # Given: the schemas returned by the singular and list control APIs
    response_models = (GetControlResponse, ControlSummary)

    # When: generating their JSON schemas
    schemas = [model.model_json_schema() for model in response_models]

    # Then: source remains backward-compatible for responses that omit the new field
    assert all("source" not in schema["required"] for schema in schemas)
    assert all(
        schema["properties"]["source"]["default"] == ControlSource.CUSTOM.value
        for schema in schemas
    )


def test_control_summary_defaults_to_custom_source() -> None:
    # Given: a legacy control summary without a source field
    payload = {"id": 1, "name": "custom-control"}

    # When: validating the summary
    summary = ControlSummary.model_validate(payload)

    # Then: the control is treated as user-created
    assert summary.source == ControlSource.CUSTOM


def test_control_summary_accepts_preset_source() -> None:
    # Given: an out-of-the-box control summary
    payload = {"id": 1, "name": "preset-control", "source": "preset"}

    # When: validating the summary
    summary = ControlSummary.model_validate(payload)

    # Then: the preset origin is preserved
    assert summary.source == ControlSource.PRESET
