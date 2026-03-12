"""Helpers for formatting nested validation field paths."""

from collections.abc import Sequence


def format_field_path(parts: Sequence[str | int]) -> str | None:
    """Format nested field parts using dot/bracket notation."""
    field = ""
    for part in parts:
        if isinstance(part, int):
            field += f"[{part}]"
            continue

        if field:
            field += "."
        field += part

    return field or None
