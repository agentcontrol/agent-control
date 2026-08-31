"""Tests for server-facing shared model contracts."""

from agent_control_models.server import ControlSummary, GetControlResponse


def test_control_response_source_is_required() -> None:
    # Given: the schemas returned by the singular and list control APIs
    response_models = (GetControlResponse, ControlSummary)

    # When: generating their JSON schemas
    required_fields = [model.model_json_schema()["required"] for model in response_models]

    # Then: clients can rely on every control response identifying its source
    assert all("source" in fields for fields in required_fields)
