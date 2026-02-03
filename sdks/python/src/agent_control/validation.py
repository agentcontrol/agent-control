"""Validation helpers for SDK inputs."""

from __future__ import annotations

from uuid import UUID


def ensure_uuid(value: str | UUID, field_name: str = "agent_id") -> UUID:
    """Return a UUID instance or raise ValueError for invalid UUID strings."""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID string") from exc


def ensure_uuid_str(value: str | UUID, field_name: str = "agent_id") -> str:
    """Return a UUID string or raise ValueError for invalid UUID strings."""
    return str(ensure_uuid(value, field_name=field_name))
