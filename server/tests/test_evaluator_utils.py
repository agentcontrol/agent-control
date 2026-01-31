"""Unit tests for evaluator_utils module."""

import pytest

from agent_control_server.services.evaluator_utils import (
    parse_evaluator_ref,
    validate_config_against_schema,
)


class TestParseEvaluatorRef:
    """Tests for parse_evaluator_ref function."""

    def test_builtin_evaluator(self) -> None:
        """Given a built-in evaluator name, when parsing, then returns None for agent."""
        # When:
        agent, name = parse_evaluator_ref("regex")

        # Then:
        assert agent is None
        assert name == "regex"

    def test_agent_scoped_evaluator(self) -> None:
        """Given an agent-scoped reference, when parsing, then returns both parts."""
        # When:
        agent, name = parse_evaluator_ref("my-agent:pii-detector")

        # Then:
        assert agent == "my-agent"
        assert name == "pii-detector"

    def test_multiple_colons(self) -> None:
        """Given a reference with multiple colons, when parsing, then splits on first colon only."""
        # When:
        agent, name = parse_evaluator_ref("my-agent:complex:name")

        # Then:
        assert agent == "my-agent"
        assert name == "complex:name"

    def test_empty_string(self) -> None:
        """Given an empty string, when parsing, then returns None agent and empty name."""
        # When:
        agent, name = parse_evaluator_ref("")

        # Then:
        assert agent is None
        assert name == ""

    def test_list_evaluator(self) -> None:
        """Given the list built-in evaluator, when parsing, then returns None for agent."""
        # When:
        agent, name = parse_evaluator_ref("list")

        # Then:
        assert agent is None
        assert name == "list"

    def test_agent_name_with_hyphens(self) -> None:
        """Given an agent name with hyphens, when parsing, then handles correctly."""
        # When:
        agent, name = parse_evaluator_ref("my-cool-agent:my-eval")

        # Then:
        assert agent == "my-cool-agent"
        assert name == "my-eval"


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
