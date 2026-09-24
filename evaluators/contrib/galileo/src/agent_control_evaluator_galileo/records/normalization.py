"""Normalize Agent Control values for canonical Galileo record fields."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from galileo_core.schemas.logging.llm import Message
from galileo_core.schemas.shared.content_parts import ContentPart, FileContentPart, TextContentPart
from galileo_core.schemas.shared.document import Document
from pydantic import BaseModel, TypeAdapter, ValidationError

_CONTENT_PART_ADAPTER: TypeAdapter[ContentPart] = TypeAdapter(ContentPart)
_MAX_SAFE_INTEGER = 2**53 - 1


class _GalileoJSONEncoder(json.JSONEncoder):
    """Serialize values using the stable subset of Splunk AO's JSON behavior."""

    def default(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(
                mode="json",
                exclude_none=True,
                exclude_unset=True,
                exclude_defaults=True,
            )
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=datetime.now().astimezone().tzinfo)
            serialized = value.isoformat()
            if value.tzinfo is not None and value.tzinfo.tzname(None) == UTC.tzname(None):
                return serialized.replace("+00:00", "Z")
            return serialized
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, UUID | Path):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return "<not serializable bytes>"
        if is_dataclass(value) and not isinstance(value, type):
            return asdict(value)
        if isinstance(value, int) and not isinstance(value, bool):
            return value if -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER else str(value)
        if isinstance(value, set | frozenset):
            return list(value)
        return f"<{type(value).__name__}>"


def _sdk_json_value(value: Any, *, active: set[int] | None = None) -> Any:
    """Apply SDK-compatible conversion recursively, including mapping keys."""
    if value is None or isinstance(value, str | bool | float):
        return value
    if isinstance(value, int):
        return value if -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER else str(value)
    if isinstance(value, UUID | Path):
        return str(value)
    if isinstance(value, datetime):
        return _GalileoJSONEncoder().default(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _sdk_json_value(value.value, active=active)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return "<not serializable bytes>"

    seen = active if active is not None else set()
    value_id = id(value)
    if value_id in seen:
        return type(value).__name__
    seen.add(value_id)
    try:
        if isinstance(value, BaseModel):
            return _sdk_json_value(
                value.model_dump(
                    mode="json",
                    exclude_none=True,
                    exclude_unset=True,
                    exclude_defaults=True,
                ),
                active=seen,
            )
        if is_dataclass(value) and not isinstance(value, type):
            return _sdk_json_value(asdict(value), active=seen)
        if isinstance(value, Mapping):
            return {
                _sdk_json_value(key, active=seen): _sdk_json_value(item, active=seen)
                for key, item in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return [_sdk_json_value(item, active=seen) for item in value]
        if isinstance(value, set | frozenset):
            return [_sdk_json_value(item, active=seen) for item in value]
        if hasattr(value, "__slots__") and value.__slots__:
            return _sdk_json_value(
                {slot: getattr(value, slot, None) for slot in value.__slots__}, active=seen
            )
        if hasattr(value, "__dict__"):
            return _sdk_json_value(
                {key: item for key, item in vars(value).items() if not key.startswith("_")},
                active=seen,
            )
        return f"<{type(value).__name__}>"
    finally:
        seen.discard(value_id)


def _json_text(value: Any) -> str:
    """Return the Galileo text representation of a structured value."""
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, bool | int | float):
        return json.dumps(value)
    return json.dumps(_sdk_json_value(value))


def _json_compatible(value: Any) -> Any:
    """Convert models and containers into values accepted by Galileo Pydantic models."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python", exclude_none=True)
    if isinstance(value, Mapping):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_compatible(item) for item in value]
    if isinstance(value, UUID | datetime | date | Enum):
        return _GalileoJSONEncoder().default(value)
    return value


def _content_part(value: Any) -> dict[str, Any] | None:
    """Validate and serialize a public Galileo text or file content part."""
    if isinstance(value, (TextContentPart, FileContentPart)):
        return value.model_dump(mode="json", exclude_none=True)
    if not isinstance(value, Mapping):
        return None
    try:
        part = _CONTENT_PART_ADAPTER.validate_python(dict(value))
    except ValidationError:
        return None
    return part.model_dump(mode="json", exclude_none=True)


def _message_content(value: Any) -> Any:
    if isinstance(value, Message):
        return value.content
    if isinstance(value, Mapping) and ("role" in value or "content" in value):
        return value.get("content", "")
    return None


def _normalize_content_items(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return None
    normalized: list[dict[str, Any]] = []
    for item in value:
        block = _content_part(item)
        if block is None:
            return None
        normalized.append(block)
    return normalized


def _message_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray) and all(
        isinstance(item, Message)
        or (isinstance(item, Mapping) and ("role" in item or "content" in item))
        for item in value
    )


def _flatten_message_sequence(value: Sequence[Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for message in value:
        content = _message_content(message)
        if isinstance(content, str):
            if content:
                blocks.append(TextContentPart(text=content).model_dump(mode="json"))
        elif isinstance(content, Sequence) and not isinstance(content, str | bytes | bytearray):
            for item in content:
                block = _content_part(item)
                if block is not None:
                    blocks.append(block)
                elif isinstance(item, str):
                    blocks.append(TextContentPart(text=item).model_dump(mode="json"))
                else:
                    # Preserve unsupported multimodal payloads instead of dropping them.
                    blocks.append(TextContentPart(text=_json_text(item)).model_dump(mode="json"))
        elif content is not None:
            blocks.append(TextContentPart(text=_json_text(content)).model_dump(mode="json"))
    return blocks


def _normalize_document(value: Any) -> Document:
    if isinstance(value, Document):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", exclude_none=True)
    if isinstance(value, Mapping):
        try:
            return Document.model_validate(dict(value))
        except ValidationError:
            return Document(content=_json_text(value))
    if isinstance(value, str):
        return Document(content=value)
    return Document(content=_json_text(value))


class GalileoRecordNormalizer:
    """Normalize destination fields for public Galileo record models.

    The normalizer owns conversions that differ by record destination. It uses
    only public ``galileo-core`` models and preserves values that cannot be
    represented natively as serialized text rather than discarding them.
    """

    @staticmethod
    def json_text(value: Any) -> str:
        """Serialize structured data while preserving strings and SDK JSON semantics."""
        return _json_text(value)

    @staticmethod
    def metadata(value: Any) -> dict[str, str]:
        """Convert metadata to the flat string mapping required by Galileo records."""
        if not isinstance(value, Mapping):
            return {}
        return {
            str(key): "None" if item is None else item if isinstance(item, str) else str(item)
            for key, item in value.items()
        }

    @classmethod
    def llm_input(cls, value: Any) -> Any:
        """Normalize an LLM input without losing any message in a sequence."""
        if value is None:
            return ""
        if isinstance(value, str | Message):
            return value
        if isinstance(value, Mapping):
            return _json_compatible(value)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            if all(isinstance(item, Message | Mapping) for item in value):
                return [_json_compatible(item) for item in value]
        return cls.json_text(value)

    @classmethod
    def llm_output(cls, value: Any) -> Any:
        """Normalize an LLM output, serializing full message sequences as one message."""
        if value is None:
            return ""
        if isinstance(value, str | Message):
            return value
        if isinstance(value, Mapping):
            return _json_compatible(value)
        if _message_sequence(value):
            return cls.json_text(value)
        return cls.json_text(value)

    @classmethod
    def llm_redacted_input(cls, value: Any) -> Any:
        return None if value is None else cls.llm_input(value)

    @classmethod
    def llm_redacted_output(cls, value: Any) -> Any:
        return None if value is None else cls.llm_output(value)

    @staticmethod
    def llm_tools(value: Any) -> Any:
        """Normalize tool definitions nested in an LLM span."""
        return None if value is None else _sdk_json_value(value)

    @classmethod
    def tool_input(cls, value: Any) -> str:
        """Serialize tool input as text, using an empty string for missing input."""
        return "" if value is None else cls.json_text(value)

    @classmethod
    def tool_output(cls, value: Any) -> str | None:
        """Serialize a present tool output as text and preserve missing output."""
        return None if value is None else cls.json_text(value)

    @classmethod
    def tool_redacted_input(cls, value: Any) -> str | None:
        return None if value is None else cls.json_text(value)

    @classmethod
    def tool_redacted_output(cls, value: Any) -> str | None:
        return None if value is None else cls.json_text(value)

    @classmethod
    def retriever_input(cls, value: Any) -> str:
        return "" if value is None else cls.json_text(value)

    @staticmethod
    def retriever_output(value: Any) -> list[Document]:
        """Convert supported retrieval values into canonical Galileo Documents."""
        if value is None:
            return [Document(content="")]
        if isinstance(value, Document):
            return [value]
        if isinstance(value, BaseModel):
            return [_normalize_document(value)]
        if isinstance(value, str):
            return [Document(content=value)]
        if isinstance(value, Mapping):
            return [_normalize_document(value)]
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            items = list(value)
            if not items:
                return []
            if all(isinstance(item, Document) for item in items):
                return list(items)
            if all(isinstance(item, str) for item in items):
                return [Document(content=item) for item in items]
            if all(isinstance(item, Mapping) for item in items):
                return [_normalize_document(item) for item in items]
            if all(isinstance(item, BaseModel) for item in items):
                return [_normalize_document(item) for item in items]
            raise ValueError(
                "Invalid document output. Expected a list of strings, dictionaries, or Documents."
            )
        return [Document(content="")]

    @classmethod
    def retriever_redacted_input(cls, value: Any) -> str | None:
        return None if value is None else cls.json_text(value)

    @classmethod
    def retriever_redacted_output(cls, value: Any) -> list[Document] | None:
        return None if value is None else cls.retriever_output(value)

    @classmethod
    def trace_input(cls, value: Any) -> Any:
        """Normalize trace input to a string or validated public content parts."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            return cls.json_text(value)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            normalized = _normalize_content_items(value)
            if normalized is not None:
                return normalized
            if all(isinstance(item, Mapping) for item in value):
                return cls.json_text(value)
            raise TypeError("Trace input must be text, a mapping, or a list of content blocks.")
        raise TypeError(f"Trace input does not support {type(value).__name__} values.")

    @classmethod
    def trace_output(cls, value: Any) -> Any:
        """Normalize trace output and flatten message sequences to content parts."""
        if value is None or isinstance(value, str):
            return value
        if _message_sequence(value):
            return _flatten_message_sequence(value)
        normalized = _normalize_content_items(value)
        if normalized is not None:
            return normalized
        return cls.json_text(value)

    @classmethod
    def trace_redacted_input(cls, value: Any) -> Any:
        return None if value is None else cls.trace_input(value)

    @classmethod
    def trace_redacted_output(cls, value: Any) -> Any:
        return None if value is None else cls.trace_output(value)

    @classmethod
    def session_input(cls, value: Any) -> Any:
        """Normalize the session input variants accepted by the public model."""
        if value is None or isinstance(value, str | Message):
            return value
        if isinstance(value, TextContentPart | FileContentPart):
            return [value]
        if isinstance(value, Document):
            return cls.json_text(value)
        if isinstance(value, BaseModel):
            return value
        if isinstance(value, Mapping):
            if "role" in value:
                return _json_compatible(value)
            part = _content_part(value)
            if part is not None:
                return [part]
            return cls.json_text(value)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            if not value:
                return []
            if all(isinstance(item, Message) for item in value):
                return list(value)
            if all(isinstance(item, Mapping) for item in value):
                if all("role" in item for item in value):
                    return [_json_compatible(item) for item in value]
            content_parts = _normalize_content_items(value)
            if content_parts is not None:
                return content_parts
            if all(isinstance(item, BaseModel) for item in value):
                return cls.json_text(value)
            return [_json_compatible(item) for item in value]
        return cls.json_text(value)

    @classmethod
    def session_output(cls, value: Any) -> Any:
        """Normalize session output while preserving messages, documents and parts."""
        if value is None or isinstance(value, str | Message):
            return value
        if isinstance(value, Document):
            return [value]
        if isinstance(value, TextContentPart | FileContentPart):
            return [value]
        if isinstance(value, BaseModel):
            return value
        if isinstance(value, Mapping):
            if "role" in value:
                return _json_compatible(value)
            if "content" in value or "page_content" in value:
                return _normalize_document(value)
            part = _content_part(value)
            if part is not None:
                return [part]
            return cls.json_text(value)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            if not value:
                return []
            if all(isinstance(item, Document) for item in value):
                return list(value)
            if all(isinstance(item, Mapping) and "role" in item for item in value):
                return _flatten_message_sequence(value)
            if all(
                isinstance(item, Mapping) and ("content" in item or "page_content" in item)
                for item in value
            ):
                return [_normalize_document(item) for item in value]
            if _message_sequence(value):
                return _flatten_message_sequence(value)
            content_parts = _normalize_content_items(value)
            if content_parts is not None:
                return content_parts
            if all(isinstance(item, Mapping) for item in value):
                return [_json_compatible(item) for item in value]
            return [_json_compatible(item) for item in value]
        return cls.json_text(value)

    @classmethod
    def session_redacted_input(cls, value: Any) -> Any:
        return None if value is None else cls.session_input(value)

    @classmethod
    def session_redacted_output(cls, value: Any) -> Any:
        return None if value is None else cls.session_output(value)

    @staticmethod
    def session_traces(
        values: Sequence[Any],
        *,
        normalize_record: Callable[[Any], Any],
    ) -> list[Any]:
        """Normalize every nested session trace through the shared record path."""
        return [normalize_record(value) for value in values]
