"""Value normalization shared by the Galileo record factory.

The conversions in this module deliberately follow the published ``splunk-ao``
helpers. The factory owns the Agent Control-to-record mapping, while the SDK
continues to own serialization and document coercion.

Orbit's scorer-input normalizer retains list-of-message dictionaries as an
intermediate LLM output, but the published ``LlmSpan`` model accepts one output
message. The factory therefore serializes the complete sequence before public
model validation; this is an intentional Orbit/SDK boundary difference, not a
last-item selection rule. Likewise, retriever ``None`` follows the SDK logger
helper (one empty document), rather than the direct model default (an empty
list).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from splunk_ao import Document, Message, SplunkAOLogger  # type: ignore[import-untyped]
from splunk_ao.utils.retrievers import convert_to_documents  # type: ignore[import-untyped]
from splunk_ao.utils.serialization import serialize_to_str  # type: ignore[import-untyped]


def text_value(value: Any, *, default: str = "") -> str:
    """Use the SDK serializer for a value that a Galileo field stores as text."""
    if value is None:
        return default
    return cast(str, serialize_to_str(value))


def tool_value(value: Any) -> str | None:
    """Serialize tool arguments/results using the SDK's canonical serializer."""
    if value is None:
        return None
    return cast(str, serialize_to_str(value))


def message_value(value: Any, *, output: bool = False) -> Any:
    """Prepare values for the public ``LlmSpan`` model.

    LLM inputs are passed through as message sequences so the canonical model
    can validate each message. The public model has a single-message output
    contract, so a list or tuple output is serialized as one complete JSON
    string. This preserves every item and lets the canonical model construct
    the assistant message.
    """
    if value is None or isinstance(value, (str, Mapping, Message)):
        return value
    if output and isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return serialize_to_str(value)
    return value


def documents(value: Any) -> Any:
    """Use the SDK retriever helper, including its fallback/error behavior.

    ``splunk_ao`` currently exposes an attrs-based ``Document`` while its
    retriever helper consumes the logging document representation. Convert
    that public resource model to its public dictionary form before delegating
    to the SDK helper; no Galileo core type is imported here.
    """
    if isinstance(value, Document):
        value = _document_dict(value)
    elif isinstance(value, list) and any(isinstance(item, Document) for item in value):
        value = [_document_dict(item) if isinstance(item, Document) else item for item in value]
    return convert_to_documents(value)


def _document_dict(value: Document) -> dict[str, Any]:
    """Convert either public SDK Document metadata representation to a dict."""
    metadata = getattr(value, "metadata", None)
    metadata_to_dict = getattr(metadata, "to_dict", None)
    if callable(metadata_to_dict):
        metadata = cast(Any, metadata_to_dict)()
    elif isinstance(metadata, Mapping):
        metadata = dict(metadata)
    else:
        metadata = None

    result: dict[str, Any] = {"content": value.content}
    if metadata is not None:
        result["metadata"] = metadata
    return result


def string_metadata(value: Any) -> dict[str, str]:
    """Apply the SDK's flat metadata conversion."""
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): "None" if item is None else item if isinstance(item, str) else str(item)
        for key, item in value.items()
    }


def trace_input_value(value: Any) -> Any:
    """Delegate trace-input coercion to the SDK logger implementation."""
    if _is_public_trace_content_parts(value):
        return value
    return _public_content_blocks(SplunkAOLogger._coerce_trace_input("input", value))


def trace_output_value(value: Any) -> Any:
    """Delegate trace-output coercion to the SDK logger implementation."""
    if value is None:
        return None
    if _is_public_trace_content_parts(value):
        return value
    return _public_content_blocks(SplunkAOLogger._coerce_output(value))


def _is_public_trace_content_parts(value: Any) -> bool:
    """Recognize content parts already emitted by a public ``Trace`` dump."""
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, Mapping):
            return False
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            continue
        if item.get("type") == "file":
            try:
                if UUID(str(item["file_id"])).version == 4:
                    continue
            except (KeyError, ValueError, AttributeError):
                pass
        return False
    return True


def _public_content_blocks(value: Any) -> Any:
    """Convert SDK ingestion blocks to the public model's content-part dicts."""
    if isinstance(value, list):
        return [
            item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
            for item in value
        ]
    return value


def session_value(value: Any) -> Any:
    """Preserve sequences accepted by the public ``Session`` validator."""
    if isinstance(value, Document):
        return _document_dict(value)
    if isinstance(value, list) and any(isinstance(item, Document) for item in value):
        return [_document_dict(item) if isinstance(item, Document) else item for item in value]
    return value
