"""Tests for isolated schema derivation logic."""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Literal
from unittest.mock import MagicMock

import agent_control._schema_derivation as schema_derivation
import pytest
from agent_control._schema_derivation import derive_schemas
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # Intentionally not defined at runtime; used to test unresolved forward-ref fallback behavior.
    class DoesNotExist: ...


class _InputModel(BaseModel):
    query: str
    limit: int = 5


class _OutputModel(BaseModel):
    answer: str


class _OrderState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class _DataPayload:
    query: str
    limit: int = 5


def golden_primitive_defaults(query: str, limit: int = 10) -> str:
    """Golden-case primitive/default function."""
    raise NotImplementedError


def golden_optional_union(conversation_id: str | None = None) -> None:
    """Golden-case optional union function."""
    raise NotImplementedError


def golden_collections(tags: list[str], metadata: dict[str, int]) -> list[str]:
    """Golden-case collection function."""
    raise NotImplementedError


def golden_nested_models(payload: _InputModel) -> _OutputModel:
    """Golden-case nested Pydantic model function."""
    raise NotImplementedError


def _resolve_local_ref(container: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local ``#/$defs/...`` refs for assertions in tests."""
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    assert ref.startswith("#/$defs/")
    def_name = ref.split("/")[-1]
    return container["$defs"][def_name]


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

    def test_keyword_only_parameters_are_included(self) -> None:
        # Given a callable with keyword-only parameters.
        def my_func(*, key: str, verbose: bool = False) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then keyword-only fields appear with expected required/default behavior.
        assert schemas.input_schema["properties"]["key"]["type"] == "string"
        assert schemas.input_schema["properties"]["verbose"]["type"] == "boolean"
        assert schemas.input_schema["properties"]["verbose"]["default"] is False
        assert set(schemas.input_schema.get("required", [])) == {"key"}

    def test_non_nullable_multi_union_input_is_preserved(self) -> None:
        # Given a callable with a non-nullable multi-member union input.
        def my_func(value: str | int) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the input union preserves both primitive branches without adding null.
        value_schema = schemas.input_schema["properties"]["value"]
        any_of = value_schema.get("anyOf")
        assert isinstance(any_of, list)
        any_of_types = {item["type"] for item in any_of}
        assert any_of_types == {"string", "integer"}

    def test_literal_input_is_emitted_as_enum(self) -> None:
        # Given a callable with a Literal-constrained input parameter.
        def my_func(mode: Literal["fast", "accurate"]) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the parameter schema is emitted as an enum.
        assert schemas.input_schema["properties"]["mode"]["enum"] == ["fast", "accurate"]

    def test_annotated_input_preserves_field_metadata(self) -> None:
        # Given a callable using Annotated with Field metadata.
        def my_func(
            query: Annotated[str, Field(description="Natural language query", min_length=3)]
        ) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then Annotated metadata is preserved in the emitted input schema.
        query_schema = schemas.input_schema["properties"]["query"]
        assert query_schema["description"] == "Natural language query"
        assert query_schema["minLength"] == 3

    def test_set_input_is_array_with_unique_items(self) -> None:
        # Given a callable with a set-typed input parameter.
        def my_func(tags: set[str]) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the set is represented as an array with uniqueItems.
        tags_schema = schemas.input_schema["properties"]["tags"]
        assert tags_schema["type"] == "array"
        assert tags_schema["uniqueItems"] is True
        assert tags_schema["items"]["type"] == "string"

    def test_tuple_input_uses_prefix_items(self) -> None:
        # Given a callable with a fixed-length tuple input parameter.
        def my_func(pair: tuple[str, int]) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then tuple structure is represented via prefixItems and tuple bounds.
        pair_schema = schemas.input_schema["properties"]["pair"]
        assert pair_schema["type"] == "array"
        assert pair_schema["minItems"] == 2
        assert pair_schema["maxItems"] == 2
        assert len(pair_schema["prefixItems"]) == 2
        assert pair_schema["prefixItems"][0]["type"] == "string"
        assert pair_schema["prefixItems"][1]["type"] == "integer"

    def test_default_none_without_optional_annotation(self) -> None:
        # Given a callable with `str` annotation but None default value.
        def my_func(query: str = None) -> str:  # type: ignore[assignment]
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then field is optional in requirements and carries a None default.
        query_schema = schemas.input_schema["properties"]["query"]
        assert query_schema["default"] is None
        assert "query" not in schemas.input_schema.get("required", [])
        assert query_schema["type"] == "string"

    def test_enum_input_schema_smoke(self) -> None:
        # Given a callable with an Enum-constrained input parameter.
        def my_func(state: _OrderState) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the enum values are preserved in the input property schema.
        state_schema = _resolve_local_ref(
            schemas.input_schema,
            schemas.input_schema["properties"]["state"],
        )
        assert state_schema["type"] == "string"
        assert state_schema["enum"] == ["pending", "approved", "rejected"]

    def test_dataclass_input_schema_smoke(self) -> None:
        # Given a callable that accepts a standard-library dataclass input.
        def my_func(payload: _DataPayload) -> str:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the dataclass shape is reflected in the input schema.
        payload_schema = _resolve_local_ref(
            schemas.input_schema,
            schemas.input_schema["properties"]["payload"],
        )
        assert payload_schema["type"] == "object"
        assert payload_schema["properties"]["query"]["type"] == "string"
        assert payload_schema["properties"]["limit"]["type"] == "integer"


class TestOutputInference:
    """Output schema derivation tests."""

    def test_primitive_output(self) -> None:
        # Given a callable with a primitive return annotation.
        def my_func() -> str:
            ...

        # When JSON schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the output schema is emitted as a string type.
        assert schemas.input_schema["type"] == "object"
        assert schemas.input_schema.get("properties") == {}
        assert schemas.input_schema.get("required", []) == []
        assert schemas.output_schema["type"] == "string"

    def test_async_function_output_derivation(self) -> None:
        # Given an async callable with typed input and output annotations.
        async def my_func(query: str) -> str:
            return query

        # When schemas are derived directly from the async function.
        schemas = derive_schemas(my_func)

        # Then input and output schemas are inferred from the annotated signature.
        assert schemas.input_schema["properties"]["query"]["type"] == "string"
        assert schemas.output_schema["type"] == "string"

    def test_literal_output_is_emitted_as_enum(self) -> None:
        # Given a callable returning a Literal-constrained value.
        def my_func() -> Literal["ok", "retry"]:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then the output schema is emitted as an enum.
        assert schemas.output_schema["enum"] == ["ok", "retry"]

    def test_any_output_is_permissive(self) -> None:
        # Given a callable explicitly annotated with Any output.
        def my_func(query: str) -> Any:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then output schema stays permissive (empty object schema).
        assert schemas.output_schema == {}

    def test_annotated_output_preserves_field_metadata(self) -> None:
        # Given a callable with Annotated return metadata.
        def my_func() -> Annotated[str, Field(description="Normalized answer")]:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then output metadata from Annotated is preserved.
        assert schemas.output_schema["type"] == "string"
        assert schemas.output_schema["description"] == "Normalized answer"

    def test_enum_output_schema_smoke(self) -> None:
        # Given a callable returning an Enum value.
        def my_func() -> _OrderState:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then output schema preserves enum value constraints.
        output_schema = _resolve_local_ref(schemas.output_schema, schemas.output_schema)
        assert output_schema["type"] == "string"
        assert output_schema["enum"] == ["pending", "approved", "rejected"]

    def test_dataclass_output_schema_smoke(self) -> None:
        # Given a callable returning a standard-library dataclass.
        def my_func(query: str) -> _DataPayload:
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then output schema reflects the dataclass field structure.
        output_schema = _resolve_local_ref(schemas.output_schema, schemas.output_schema)
        assert output_schema["type"] == "object"
        assert output_schema["properties"]["query"]["type"] == "string"
        assert output_schema["properties"]["limit"]["type"] == "integer"


class TestFunctionUnwrapBehavior:
    """unwrap() behavior for decorated callables."""

    def test_wrapped_function_uses_unwrapped_signature(self) -> None:
        # Given a wrapped function where only the unwrapped callable has useful type hints.
        def base(query: str, limit: int = 3) -> str:
            ...

        @functools.wraps(base)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return base(*args, **kwargs)

        # When schemas are derived from the wrapped callable.
        schemas = derive_schemas(wrapped)

        # Then derive_schemas() uses inspect.unwrap() and reflects the base signature.
        assert set(schemas.input_schema["properties"]) == {"query", "limit"}
        assert set(schemas.input_schema.get("required", [])) == {"query"}
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

    def test_args_schema_override_wins_for_wrapped_function(self) -> None:
        # Given a wrapped function with args_schema on the wrapper and typed signature on the base.
        class _WrapperArgsSchema:
            @staticmethod
            def model_json_schema() -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                }

        def base(query: str, limit: int = 3) -> str:
            ...

        @functools.wraps(base)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return base(*args, **kwargs)

        wrapped.args_schema = _WrapperArgsSchema()  # type: ignore[attr-defined]

        # When schemas are derived from the wrapped callable.
        schemas = derive_schemas(wrapped)

        # Then wrapper args_schema is used for input while output is inferred from unwrapped return.
        assert schemas.input_schema == {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        assert schemas.output_schema["type"] == "string"


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
        def my_func(query: DoesNotExist) -> str:
            ...

        # When schema derivation attempts to resolve type hints.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then both schemas fall back to permissive defaults and a warning is emitted.
        assert schemas.input_schema == {"type": "object", "additionalProperties": True}
        assert schemas.output_schema == {}
        assert "failed to resolve type hints" in caplog.text


class TestAdditionalFallbackBranches:
    """Additional branch coverage for defensive schema fallback paths."""

    def test_args_schema_without_model_json_schema_is_ignored(self) -> None:
        # Given a callable with an args_schema object that is missing model_json_schema().
        class _MissingArgsSchemaMethod:
            pass

        def my_func(query: str) -> str:
            ...

        my_func.args_schema = _MissingArgsSchemaMethod()  # type: ignore[attr-defined]

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then derivation ignores args_schema and falls back to signature inference.
        assert schemas.input_schema["properties"]["query"]["type"] == "string"
        assert schemas.output_schema == {"type": "string"}

    def test_args_schema_non_dict_warns_and_falls_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given a callable whose args_schema returns a non-dict payload.
        class _NonDictArgsSchema:
            @staticmethod
            def model_json_schema() -> list[str]:
                return ["not-a-dict"]

        def my_func(query: str) -> str:
            ...

        my_func.args_schema = _NonDictArgsSchema()  # type: ignore[attr-defined]

        # When schemas are derived with warning capture.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then derivation warns and uses signature-based input inference.
        assert schemas.input_schema["properties"]["query"]["type"] == "string"
        assert "returned non-dict" in caplog.text

    def test_args_schema_override_kept_when_type_hints_resolution_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given a callable with args_schema override but unresolved type hints.
        class _GoodArgsSchema:
            @staticmethod
            def model_json_schema() -> dict[str, Any]:
                return {"type": "object", "properties": {"q": {"type": "string"}}}

        def my_func(query: DoesNotExist) -> str:
            ...

        my_func.args_schema = _GoodArgsSchema()  # type: ignore[attr-defined]

        # When derivation attempts to resolve type hints.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then input stays overridden while output falls back with warning.
        assert schemas.input_schema == {"type": "object", "properties": {"q": {"type": "string"}}}
        assert schemas.output_schema == {}
        assert "failed to resolve type hints" in caplog.text

    def test_signature_inspection_failure_uses_input_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given inspect.signature raises while deriving input fields.
        def _broken_signature(_func: Any) -> Any:
            raise RuntimeError("signature failed")

        def my_func(query: str) -> str:
            ...

        monkeypatch.setattr(schema_derivation.inspect, "signature", _broken_signature)

        # When schemas are derived.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then input falls back to permissive schema and warning is emitted.
        assert schemas.input_schema == {"type": "object", "additionalProperties": True}
        assert "failed to inspect function signature" in caplog.text

    def test_self_cls_varargs_and_kwargs_are_excluded_from_input_schema(self) -> None:
        # Given a callable containing self/cls placeholders and variadic parameters.
        def my_func(self, cls, query: str, *args: Any, **kwargs: Any) -> str:  # noqa: ANN001
            ...

        # When schemas are derived.
        schemas = derive_schemas(my_func)

        # Then only concrete named fields remain in the inferred input schema.
        assert set(schemas.input_schema["properties"]) == {"query"}
        assert schemas.input_schema.get("required") == ["query"]

    def test_input_model_creation_failure_uses_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given dynamic input model creation raises unexpectedly.
        def _broken_create_model(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("create_model failed")

        def my_func(query: str) -> str:
            ...

        monkeypatch.setattr(schema_derivation, "create_model", _broken_create_model)

        # When schemas are derived.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then derivation emits warning and returns permissive input fallback.
        assert schemas.input_schema == {"type": "object", "additionalProperties": True}
        assert "failed to infer schema from signature" in caplog.text

    def test_input_non_dict_schema_from_model_uses_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given create_model returns a model whose model_json_schema() is non-dict.
        class _NonDictModel:
            @staticmethod
            def model_json_schema() -> list[str]:
                return ["not-a-dict"]

        def _fake_create_model(*_args: Any, **_kwargs: Any) -> _NonDictModel:
            return _NonDictModel()

        def my_func(query: str) -> str:
            ...

        monkeypatch.setattr(schema_derivation, "create_model", _fake_create_model)

        # When schemas are derived.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then input inference falls back after warning about non-dict schema output.
        assert schemas.input_schema == {"type": "object", "additionalProperties": True}
        assert "inferred input schema is not a dict" in caplog.text

    def test_output_type_adapter_failure_uses_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given output TypeAdapter json_schema() raises unexpectedly.
        class _BrokenTypeAdapter:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

            @staticmethod
            def json_schema() -> dict[str, Any]:
                raise RuntimeError("adapter failed")

        def my_func(query: str) -> str:
            ...

        monkeypatch.setattr(schema_derivation, "TypeAdapter", _BrokenTypeAdapter)

        # When schemas are derived.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then output derivation falls back and emits a warning.
        assert schemas.output_schema == {}
        assert "failed to infer output schema from return annotation" in caplog.text

    def test_output_non_dict_schema_from_type_adapter_uses_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given output TypeAdapter returns a non-dict JSON schema.
        class _NonDictTypeAdapter:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

            @staticmethod
            def json_schema() -> list[str]:
                return ["not-a-dict"]

        def my_func(query: str) -> str:
            ...

        monkeypatch.setattr(schema_derivation, "TypeAdapter", _NonDictTypeAdapter)

        # When schemas are derived.
        with caplog.at_level(logging.WARNING):
            schemas = derive_schemas(my_func)

        # Then output derivation falls back after warning about non-dict schema output.
        assert schemas.output_schema == {}
        assert "inferred output schema is not a dict" in caplog.text


class TestGoldenSchemas:
    """Golden-style schema snapshots for representative function signatures."""

    def test_golden_primitive_defaults_snapshot(self) -> None:
        # Given a primitive+default function with stable module-level identity.
        # When schemas are derived.
        schemas = derive_schemas(golden_primitive_defaults)

        # Then the full input/output schema snapshots match exactly.
        assert schemas.input_schema == {
            "properties": {
                "query": {"title": "Query", "type": "string"},
                "limit": {"default": 10, "title": "Limit", "type": "integer"},
            },
            "required": ["query"],
            "title": "tests_test_schema_derivation_golden_primitive_defaults_Input",
            "type": "object",
        }
        assert schemas.output_schema == {"type": "string"}


class TestJsonSchemaContract:
    """Validate derived schemas are valid JSON Schemas."""

    def test_derived_schemas_are_json_schema_valid(self) -> None:
        # Given a representative set of callables and their derived schemas.
        jsonschema = pytest.importorskip("jsonschema")
        draft202012_validator = jsonschema.Draft202012Validator

        def enum_case(state: _OrderState) -> _OrderState:
            ...

        def tuple_case(pair: tuple[str, int]) -> tuple[str, int]:
            ...

        def dataclass_case(payload: _DataPayload) -> _DataPayload:
            ...

        async def async_case(message: str) -> str:
            return message

        cases = [
            golden_primitive_defaults,
            golden_optional_union,
            golden_collections,
            golden_nested_models,
            enum_case,
            tuple_case,
            dataclass_case,
            async_case,
        ]

        # When each callable is passed through schema derivation.
        for func in cases:
            schemas = derive_schemas(func)

            # Then both input and output schemas pass Draft 2020-12 structural validation.
            draft202012_validator.check_schema(schemas.input_schema)
            draft202012_validator.check_schema(schemas.output_schema)

    def test_golden_optional_union_snapshot(self) -> None:
        # Given an optional-union input and explicit `None` return annotation.
        # When schemas are derived.
        schemas = derive_schemas(golden_optional_union)

        # Then the full schema snapshots preserve nullable input and null output types.
        assert schemas.input_schema == {
            "properties": {
                "conversation_id": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "Conversation Id",
                }
            },
            "title": "tests_test_schema_derivation_golden_optional_union_Input",
            "type": "object",
        }
        assert schemas.output_schema == {"type": "null"}

    def test_golden_collection_snapshot(self) -> None:
        # Given list/dict input collections and a list return annotation.
        # When schemas are derived.
        schemas = derive_schemas(golden_collections)

        # Then the full schema snapshots preserve array/object structures exactly.
        assert schemas.input_schema == {
            "properties": {
                "tags": {"items": {"type": "string"}, "title": "Tags", "type": "array"},
                "metadata": {
                    "additionalProperties": {"type": "integer"},
                    "title": "Metadata",
                    "type": "object",
                },
            },
            "required": ["tags", "metadata"],
            "title": "tests_test_schema_derivation_golden_collections_Input",
            "type": "object",
        }
        assert schemas.output_schema == {"items": {"type": "string"}, "type": "array"}

    def test_golden_nested_pydantic_model_snapshot(self) -> None:
        # Given nested Pydantic input/output models.
        # When schemas are derived.
        schemas = derive_schemas(golden_nested_models)

        # Then `$defs` and `$ref` are preserved in the exact schema snapshot.
        assert schemas.input_schema == {
            "$defs": {
                "_InputModel": {
                    "properties": {
                        "query": {"title": "Query", "type": "string"},
                        "limit": {"default": 5, "title": "Limit", "type": "integer"},
                    },
                    "required": ["query"],
                    "title": "_InputModel",
                    "type": "object",
                }
            },
            "properties": {"payload": {"$ref": "#/$defs/_InputModel"}},
            "required": ["payload"],
            "title": "tests_test_schema_derivation_golden_nested_models_Input",
            "type": "object",
        }
        assert schemas.output_schema == {
            "properties": {"answer": {"title": "Answer", "type": "string"}},
            "required": ["answer"],
            "title": "_OutputModel",
            "type": "object",
        }

    def test_golden_args_schema_override_snapshot(self) -> None:
        # Given a callable with an explicit framework-style args_schema override.
        class _GoldenArgsSchema:
            @staticmethod
            def model_json_schema() -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["q"],
                }

        def golden_args_schema_override(query: str) -> str:
            raise NotImplementedError

        golden_args_schema_override.args_schema = _GoldenArgsSchema()  # type: ignore[attr-defined]

        # When schemas are derived.
        schemas = derive_schemas(golden_args_schema_override)

        # Then the full input snapshot is sourced from args_schema and output remains inferred.
        assert schemas.input_schema == {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["q"],
        }
        assert schemas.output_schema == {"type": "string"}
