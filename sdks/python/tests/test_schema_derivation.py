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
        def my_func(query: str, limit: int = 10) -> str:
            ...

        schemas = derive_schemas(my_func)

        assert schemas.input_schema["type"] == "object"
        assert set(schemas.input_schema.get("required", [])) == {"query"}
        assert schemas.input_schema["properties"]["query"]["type"] == "string"
        assert schemas.input_schema["properties"]["limit"]["type"] == "integer"

    def test_optional_union_parameter_is_preserved(self) -> None:
        def my_func(query: str, conversation_id: str | None = None) -> str:
            ...

        schemas = derive_schemas(my_func)

        conversation_schema = schemas.input_schema["properties"]["conversation_id"]
        has_null = "anyOf" in conversation_schema or (
            isinstance(conversation_schema.get("type"), list)
            and "null" in conversation_schema["type"]
        )
        assert has_null

    def test_collection_types_are_represented(self) -> None:
        def my_func(tags: list[str], metadata: dict[str, int]) -> list[str]:
            ...

        schemas = derive_schemas(my_func)

        assert schemas.input_schema["properties"]["tags"]["type"] == "array"
        assert schemas.input_schema["properties"]["metadata"]["type"] == "object"
        assert schemas.output_schema["type"] == "array"

    def test_untyped_parameters_fall_back_to_any_fields(self) -> None:
        def my_func(x, y):
            ...

        schemas = derive_schemas(my_func)

        assert schemas.input_schema["type"] == "object"
        assert set(schemas.input_schema["properties"]) == {"x", "y"}


class TestOutputInference:
    """Output schema derivation tests."""

    def test_primitive_output(self) -> None:
        def my_func() -> str:
            ...

        schemas = derive_schemas(my_func)

        assert schemas.output_schema["type"] == "string"

    def test_pydantic_input_and_output(self) -> None:
        def my_func(payload: _InputModel) -> _OutputModel:
            ...

        schemas = derive_schemas(my_func)

        payload_schema = schemas.input_schema["properties"]["payload"]
        assert ("type" in payload_schema and payload_schema["type"] == "object") or (
            "$ref" in payload_schema
        )
        assert schemas.output_schema["type"] == "object"


class TestArgsSchemaOverride:
    """args_schema precedence and fallback behavior."""

    def test_args_schema_precedence(self) -> None:
        mock_schema = MagicMock()
        mock_schema.model_json_schema.return_value = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }

        def my_func(query: str) -> str:
            ...

        my_func.args_schema = mock_schema  # type: ignore[attr-defined]

        schemas = derive_schemas(my_func)

        assert schemas.input_schema == {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        mock_schema.model_json_schema.assert_called_once()

    def test_args_schema_failure_falls_back_to_signature_inference(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class BrokenArgsSchema:
            def model_json_schema(self) -> dict[str, Any]:
                raise RuntimeError("broken args schema")

        def my_func(query: str) -> str:
            ...

        my_func.args_schema = BrokenArgsSchema()  # type: ignore[attr-defined]

        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        assert schemas.input_schema["properties"]["query"]["type"] == "string"
        assert "args_schema.model_json_schema() failed" in caplog.text


class TestFallbackWarnings:
    """Warnings and fallback behavior for unresolved/incomplete typing."""

    def test_missing_return_annotation_warns_and_falls_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def my_func(query: str):
            ...

        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        assert schemas.output_schema == {}
        assert "missing return type annotation" in caplog.text

    def test_unresolved_type_hints_warn_and_fall_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def my_func(query: "DoesNotExist") -> str:
            ...

        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        assert schemas.input_schema == {"type": "object", "additionalProperties": True}
        assert schemas.output_schema == {}
        assert "failed to resolve type hints" in caplog.text
