"""Validation helpers for SDK inputs."""

from __future__ import annotations

import re

_AGENT_NAME_MIN_LENGTH = 10
_AGENT_NAME_REGEX = re.compile(r"^[a-z0-9:_-]+$")


def ensure_agent_name(value: str, field_name: str = "agent_name") -> str:
    """Return normalized agent name or raise ValueError for invalid values."""
    normalized = str(value).strip().lower()
    if len(normalized) < _AGENT_NAME_MIN_LENGTH:
        raise ValueError(
            f"{field_name} must be at least {_AGENT_NAME_MIN_LENGTH} characters long"
        )
    if not _AGENT_NAME_REGEX.fullmatch(normalized):
        raise ValueError(
            f"{field_name} may only contain lowercase letters, digits, ':', '_' or '-'"
        )
    return normalized
