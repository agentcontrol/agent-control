"""Tests for isolated schema derivation logic."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agent_control._schema_derivation import derive_schemas


class _InputModel(BaseModel):
    query: str
    limit: int = 5


class _OutputModel(BaseModel):
    answer: str


class TestInputInference:
    """Input schema derivation tests."""

    def test_required_and_default_parameters(self) -> None:
        # Given a callable with one required parameter and one parameter with a default.
        def my_func(query: str, limit: int = 10) -> str:
            ...

        # When JSON schemas are derived from the function signature.
        schemas = derive_schemas(my_func)

        # Then the input schema marks only the required field as required and preserves types.
        assert schemas.input_schema["type"] == "object"
        assert set(schemas.input_schema.get("required", [])) == {"query"}
        assert schemas.input_schema["properties"]["query"]["type"] == "string"
        assert schemas.input_schema["properties"]["limit"]["type"] == "integer"

    def test_optional_union_parameter_is_preserved(self) -> None:
        # Given a callable with an optional union parameter (`str | None`).
        def my_func(query: str, conversation_id: str | None = None) -> str:
            ...

        # When JSON schemas are derived from that signature.
        schemas = derive_schemas(my_func)

        # Then the derived property schema includes a nullable representation.
        conversation_schema = schemas.input_schema["properties"]["conversation_id"]
        has_null = "anyOf" in conversation_schema or (
            isinstance(conversation_schema.get("type"), list)
            and "null" in conversation_schema["type"]
        )
        assert has_null

    def test_collection_types_are_represented(self) -> None:
        # Given collection-typed inputs and a collection-typed return annotation.
        def my_func(tags: list[str], metadata: dict[str, int]) -> list[str]:
            ...

        # When JSON schemas are derived.
        schemas = derive_schemas(my_func)

        # Then list/dict/return collection types are preserved in the emitted schemas.
        assert schemas.input_schema["properties"]["tags"]["type"] == "array"
        assert schemas.input_schema["properties"]["metadata"]["type"] == "object"
        assert schemas.output_schema["type"] == "array"

    def test_untyped_parameters_fall_back_to_any_fields(self) -> None:
        # Given a callable with untyped parameters.
        def my_func(x, y):
            ...

        # When JSON schemas are derived.
        schemas = derive_schemas(my_func)

        # Then schema derivation still exposes both fields under a permissive object schema.
        assert schemas.input_schema["type"] == "object"
        assert set(schemas.input_schema["properties"]) == {"x", "y"}


class TestOutputInference:
    """Output schema derivation tests."""

    def test_primitive_output(self) -> None:
        # Given a callable with a primitive return annotation.
        def my_func() -> str:
            ...

        # When JSON schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the output schema is emitted as a string type.
        assert schemas.output_schema["type"] == "string"

    def test_pydantic_input_and_output(self) -> None:
        # Given a callable that uses Pydantic models for input and output.
        def my_func(payload: _InputModel) -> _OutputModel:
            ...

        # When JSON schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the payload is represented as an object/$ref and the output resolves to object.
        payload_schema = schemas.input_schema["properties"]["payload"]
        assert ("type" in payload_schema and payload_schema["type"] == "object") or (
            "$ref" in payload_schema
        )
        assert schemas.output_schema["type"] == "object"


class TestArgsSchemaOverride:
    """args_schema precedence and fallback behavior."""

    def test_args_schema_precedence(self) -> None:
        # Given a callable that provides a working args_schema override.
        mock_schema = MagicMock()
        mock_schema.model_json_schema.return_value = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }

        def my_func(query: str) -> str:
            ...

        my_func.args_schema = mock_schema  # type: ignore[attr-defined]

        # When schemas are derived for the callable.
        schemas = derive_schemas(my_func)

        # Then args_schema is used as the authoritative input schema source.
        assert schemas.input_schema == {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        mock_schema.model_json_schema.assert_called_once()

    def test_args_schema_failure_falls_back_to_signature_inference(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given a callable whose args_schema override raises at schema generation time.
        class BrokenArgsSchema:
            def model_json_schema(self) -> dict[str, Any]:
                raise RuntimeError("broken args schema")

        def my_func(query: str) -> str:
            ...

        my_func.args_schema = BrokenArgsSchema()  # type: ignore[attr-defined]

        # When schema derivation runs with warning capture enabled.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then derivation falls back to signature inference and emits a warning.
        assert schemas.input_schema["properties"]["query"]["type"] == "string"
        assert "args_schema.model_json_schema() failed" in caplog.text


class TestFallbackWarnings:
    """Warnings and fallback behavior for unresolved/incomplete typing."""

    def test_missing_return_annotation_warns_and_falls_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given a callable without an explicit return type annotation.
        def my_func(query: str):
            ...

        # When schemas are derived while warnings are captured.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then output falls back to a permissive schema and a warning is emitted.
        assert schemas.output_schema == {}
        assert "missing return type annotation" in caplog.text

    def test_unresolved_type_hints_warn_and_fall_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given a callable that references an unresolved forward type hint.
        def my_func(query: "DoesNotExist") -> str:
            ...

        # When schema derivation attempts to resolve type hints.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then both schemas fall back to permissive defaults and a warning is emitted.
        assert schemas.input_schema == {"type": "object", "additionalProperties": True}
        assert schemas.output_schema == {}
        assert "failed to resolve type hints" in caplog.text
