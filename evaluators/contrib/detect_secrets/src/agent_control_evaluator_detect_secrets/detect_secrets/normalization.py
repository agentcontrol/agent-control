"""Payload normalization helpers for the detect-secrets evaluator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

NormalizedPayloadType = Literal["none", "str", "dict", "list", "primitive"]


class NormalizationError(ValueError):
    """Raised when selector-selected payloads cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class NormalizedPayload:
    """Normalized text payload and line-to-JSON-pointer metadata."""

    payload_type: NormalizedPayloadType
    text: str | None
    line_locations_by_line: dict[int, LineLocation]


@dataclass(frozen=True, slots=True)
class LineLocation:
    """Safe structured-location metadata for a rendered line."""

    json_pointer: str | None
    parent_pointer: str | None = None
    key_probe_text: str | None = None
    key_name: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedLine:
    """A rendered JSON line plus optional structural pointer metadata."""

    text: str
    location: LineLocation | None = None


def _json_dumps(value: Any, **kwargs: Any) -> str:
    """Serialize JSON while keeping Unicode line separators escaped on one logical line."""
    dumped = json.dumps(value, **kwargs)
    return dumped.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def normalize_payload(data: Any) -> NormalizedPayload:
    """Normalize selector output to deterministic text for detect-secrets scanning."""
    if data is None:
        return NormalizedPayload(payload_type="none", text=None, line_locations_by_line={})

    if isinstance(data, str):
        return NormalizedPayload(payload_type="str", text=data, line_locations_by_line={})

    if isinstance(data, dict):
        return _normalize_structured_payload(data, payload_type="dict")

    if isinstance(data, list | tuple):
        return _normalize_structured_payload(data, payload_type="list")

    if isinstance(data, bool | int | float):
        return _normalize_primitive_payload(data)

    raise NormalizationError(f"Unsupported payload type for normalization: {type(data).__name__}")


def apply_line_exclusions(text: str, patterns: tuple[Any, ...]) -> str:
    """Blank matching lines without changing line numbering."""
    if not patterns:
        return text

    filtered_lines = [
        "" if any(pattern.search(line) for pattern in patterns) else line
        for line in text.splitlines()
    ]
    return "\n".join(filtered_lines)


def _normalize_structured_payload(
    data: dict[Any, Any] | list[Any] | tuple[Any, ...],
    *,
    payload_type: Literal["dict", "list"],
) -> NormalizedPayload:
    try:
        normalized_data = _normalize_json_value(data)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"Failed to normalize structured payload: {exc}") from exc

    try:
        text = _json_dumps(
            normalized_data,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"Failed to normalize structured payload: {exc}") from exc

    try:
        rendered_lines = _render_json_lines(normalized_data)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"Failed to map structured payload lines: {exc}") from exc

    rendered_text = "\n".join(line.text for line in rendered_lines)
    if rendered_text != text:
        raise NormalizationError("Structured payload rendering mismatch during normalization")

    line_locations_by_line = {
        line_number: rendered_line.location
        for line_number, rendered_line in enumerate(rendered_lines, start=1)
        if rendered_line.location is not None
    }
    return NormalizedPayload(
        payload_type=payload_type,
        text=text,
        line_locations_by_line=line_locations_by_line,
    )


def _normalize_primitive_payload(data: bool | int | float) -> NormalizedPayload:
    try:
        text = _json_dumps(data, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"Failed to normalize scalar payload: {exc}") from exc

    return NormalizedPayload(payload_type="primitive", text=text, line_locations_by_line={})


def _normalize_json_value(value: Any) -> Any:
    """Convert supported Python payloads into a deterministic JSON-compatible shape."""
    if isinstance(value, dict):
        normalized_object: dict[str, Any] = {}
        for raw_key, child in value.items():
            normalized_key = _json_object_key_name(raw_key)
            if normalized_key in normalized_object:
                raise ValueError(f"JSON key collision after normalization: {normalized_key!r}")
            normalized_object[normalized_key] = _normalize_json_value(child)
        return normalized_object

    if isinstance(value, list | tuple):
        return [_normalize_json_value(child) for child in value]

    return value


def _render_json_lines(
    value: Any,
    *,
    indent_level: int = 0,
    prefix: str = "",
    pointer: str = "",
) -> list[RenderedLine]:
    indent = " " * (indent_level * 2)

    if isinstance(value, dict):
        return _render_dict_lines(value, indent_level=indent_level, prefix=prefix, pointer=pointer)

    if isinstance(value, list | tuple):
        return _render_list_lines(value, indent_level=indent_level, prefix=prefix, pointer=pointer)

    scalar_text = _json_dumps(value, ensure_ascii=False, allow_nan=False)
    scalar_pointer = pointer or None
    return [
        RenderedLine(
            text=f"{indent}{prefix}{scalar_text}",
            location=LineLocation(json_pointer=scalar_pointer),
        )
    ]


def _render_dict_lines(
    value: dict[Any, Any],
    *,
    indent_level: int,
    prefix: str,
    pointer: str,
) -> list[RenderedLine]:
    indent = " " * (indent_level * 2)
    if not value:
        return [RenderedLine(text=f"{indent}{prefix}{{}}")]

    lines = [RenderedLine(text=f"{indent}{prefix}{{")]
    items = sorted(value.items(), key=lambda item: _json_object_key_name(item[0]))
    last_index = len(items) - 1

    for index, (raw_key, child) in enumerate(items):
        suffix = "," if index < last_index else ""
        key_name = _json_object_key_name(raw_key)
        key_literal = _json_dumps(key_name, ensure_ascii=False, allow_nan=False)
        child_prefix = f"{key_literal}: "
        child_pointer = _append_json_pointer(pointer, key_name)
        child_lines = _render_json_lines(
            child,
            indent_level=indent_level + 1,
            prefix=child_prefix,
            pointer=child_pointer,
        )
        child_lines = _attach_dict_child_location(
            child=child,
            child_lines=child_lines,
            child_pointer=child_pointer,
            parent_pointer=pointer if pointer else "",
            key_literal=key_literal,
            key_name=key_name,
        )
        child_lines[-1] = RenderedLine(
            text=f"{child_lines[-1].text}{suffix}",
            location=child_lines[-1].location,
        )
        lines.extend(child_lines)

    lines.append(RenderedLine(text=f"{indent}}}"))
    return lines


def _render_list_lines(
    value: list[Any] | tuple[Any, ...],
    *,
    indent_level: int,
    prefix: str,
    pointer: str,
) -> list[RenderedLine]:
    indent = " " * (indent_level * 2)
    if not value:
        return [RenderedLine(text=f"{indent}{prefix}[]")]

    lines = [RenderedLine(text=f"{indent}{prefix}[")]
    last_index = len(value) - 1

    for index, child in enumerate(value):
        suffix = "," if index < last_index else ""
        child_pointer = _append_json_pointer(pointer, str(index))
        child_lines = _render_json_lines(
            child,
            indent_level=indent_level + 1,
            prefix="",
            pointer=child_pointer,
        )
        child_lines = _attach_list_child_location(child, child_lines, child_pointer)
        child_lines[-1] = RenderedLine(
            text=f"{child_lines[-1].text}{suffix}",
            location=child_lines[-1].location,
        )
        lines.extend(child_lines)

    lines.append(RenderedLine(text=f"{indent}]"))
    return lines


def _json_object_key_name(key: Any) -> str:
    if isinstance(key, str):
        return key
    if key is True:
        return "true"
    if key is False:
        return "false"
    if key is None:
        return "null"
    if isinstance(key, int | float):
        return _json_dumps(key, ensure_ascii=False, allow_nan=False)
    raise TypeError(f"Unsupported JSON object key type: {type(key).__name__}")


def _attach_dict_child_location(
    child: Any,
    child_lines: list[RenderedLine],
    child_pointer: str,
    parent_pointer: str | None,
    key_literal: str,
    key_name: str,
) -> list[RenderedLine]:
    if child_lines:
        first_line = child_lines[0]
        child_lines[0] = RenderedLine(
            text=first_line.text,
            location=LineLocation(
                json_pointer=child_pointer,
                parent_pointer=parent_pointer,
                key_probe_text=_build_key_probe_text(key_literal, child),
                key_name=key_name,
            ),
        )
    return child_lines


def _attach_list_child_location(
    child: Any,
    child_lines: list[RenderedLine],
    child_pointer: str,
) -> list[RenderedLine]:
    if isinstance(child, dict | list) and child_lines:
        first_line = child_lines[0]
        child_lines[0] = RenderedLine(
            text=first_line.text,
            location=LineLocation(json_pointer=child_pointer),
        )
    return child_lines


def _build_key_probe_text(key_literal: str, child: Any) -> str:
    if isinstance(child, dict):
        return f"{key_literal}: {{}}"
    if isinstance(child, list):
        return f"{key_literal}: []"
    return f"{key_literal}: null"


def _append_json_pointer(pointer: str, segment: str) -> str:
    escaped = segment.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}" if pointer else f"/{escaped}"
