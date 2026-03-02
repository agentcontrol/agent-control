"""Unit tests for evaluator_utils module."""

import pytest

from agent_control_server.services.evaluator_utils import (
    is_agent_scoped,
    parse_evaluator_ref_full,
    validate_config_against_schema,
)


class TestParseEvaluatorRefFull:
    """Tests for parse_evaluator_ref_full function (full three-way parsing)."""

    def test_builtin_evaluator(self) -> None:
        """Given a built-in evaluator, when parsing full, then type is builtin."""
        # When
        result = parse_evaluator_ref_full("regex")

        # Then
        assert result.type == "builtin"
        assert result.name == "regex"
        assert result.namespace is None
        assert result.local_name == "regex"

    def test_external_evaluator(self) -> None:
        """Given an external evaluator, when parsing full, then type is external."""
        # When
        result = parse_evaluator_ref_full("galileo.luna2")

        # Then
        assert result.type == "external"
        assert result.name == "galileo.luna2"
        assert result.namespace == "galileo"
        assert result.local_name == "luna2"

    def test_agent_scoped_evaluator(self) -> None:
        """Given an agent-scoped evaluator, when parsing full, then type is agent."""
        # When
        result = parse_evaluator_ref_full("my-agent:pii-detector")

        # Then
        assert result.type == "agent"
        assert result.name == "my-agent:pii-detector"
        assert result.namespace == "my-agent"
        assert result.local_name == "pii-detector"

    def test_external_with_nested_path(self) -> None:
        """Given an external evaluator with nested path, when parsing, splits on first dot."""
        # When
        result = parse_evaluator_ref_full("acme.safety.toxicity")

        # Then
        assert result.type == "external"
        assert result.namespace == "acme"
        assert result.local_name == "safety.toxicity"

    def test_agent_scoped_with_dot_in_name(self) -> None:
        """Given agent-scoped with dot in name, when parsing, then colon takes precedence."""
        # When - colon should be detected before dot
        result = parse_evaluator_ref_full("my-agent:vendor.eval")

        # Then
        assert result.type == "agent"
        assert result.namespace == "my-agent"
        assert result.local_name == "vendor.eval"


class TestIsAgentScoped:
    """Tests for is_agent_scoped helper function."""

    def test_builtin_not_agent_scoped(self) -> None:
        """Given a built-in evaluator, when checking, then returns False."""
        assert is_agent_scoped("regex") is False

    def test_external_not_agent_scoped(self) -> None:
        """Given an external evaluator, when checking, then returns False."""
        assert is_agent_scoped("galileo.luna2") is False

    def test_agent_scoped_returns_true(self) -> None:
        """Given an agent-scoped evaluator, when checking, then returns True."""
        assert is_agent_scoped("my-agent:pii-detector") is True


class TestValidateConfigAgainstSchema:
    """Tests for validate_config_against_schema function."""

    def test_empty_schema_accepts_anything(self) -> None:
        """Given an empty schema, when validating any config, then no error is raised."""
        # Given:
        schema = {}
        config = {"any": "value", "nested": {"key": 123}}

        # When:/Then - no exception
        validate_config_against_schema(config, schema)

    def test_valid_config(self) -> None:
        """Given a schema, when config matches schema, then no error is raised."""
        # Given:
        schema = {
            "type": "object",
            "properties": {"threshold": {"type": "number"}},
            "required": ["threshold"],
        }
        config = {"threshold": 0.5}

        # When:/Then - no exception
        validate_config_against_schema(config, schema)

    def test_invalid_config_missing_required(self) -> None:
        """Given a schema with required field, when config missing it, then raises error."""
        # Given:
        schema = {
            "type": "object",
            "properties": {"threshold": {"type": "number"}},
            "required": ["threshold"],
        }
        config = {}

        # When:/Then
        with pytest.raises(Exception) as exc_info:
            validate_config_against_schema(config, schema)
        assert "threshold" in str(exc_info.value)

    def test_invalid_config_wrong_type(self) -> None:
        """Given a schema expecting number, when config has string, then raises error."""
        # Given:
        schema = {
            "type": "object",
            "properties": {"value": {"type": "number"}},
        }
        config = {"value": "not-a-number"}

        # When:/Then
        with pytest.raises(Exception):
            validate_config_against_schema(config, schema)

    def test_nested_object_validation(self) -> None:
        """Given a schema with nested object, when config is valid, then no error."""
        # Given:
        schema = {
            "type": "object",
            "properties": {
                "settings": {
                    "type": "object",
                    "properties": {"level": {"type": "integer"}},
                }
            },
        }
        config = {"settings": {"level": 5}}

        # When:/Then - no exception
        validate_config_against_schema(config, schema)

    def test_config_with_extra_properties(self) -> None:
        """Given a schema without additionalProperties:false, when config has extras, then ok."""
        # Given:
        schema = {
            "type": "object",
            "properties": {"known": {"type": "string"}},
        }
        config = {"known": "value", "extra": "ignored"}

        # When:/Then - no exception (additionalProperties defaults to true)
        validate_config_against_schema(config, schema)
